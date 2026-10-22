"""Per-system ticks from the system's own readings: influence or states only
change at a tick, so differing readings prove the system ticked between them
(tick.edcd.io listed no tick for 2026-10-18 while Ekono still moved)."""
from edc.core.system_ticks import infer_system_ticks, merge_ticks

EXP = '[{"State": "Expansion"}]'


def _r(at, inf, source="eddn", active="[]", pending="[]", faction="EUW"):
    return (at, faction, inf, active, pending, source)


def test_change_between_readings_is_a_system_tick():
    rows = [_r("2026-10-18T23:10:36Z", 0.7812), _r("2026-10-18T23:10:36Z", 0.05, faction="Other"),
            _r("2026-10-19T11:46:38Z", 0.7832), _r("2026-10-19T11:46:38Z", 0.048, faction="Other"),
            _r("2026-10-19T15:00:00Z", 0.7832)]                                         # confirms it
    assert infer_system_ticks(rows) == [{"after": "2026-10-18T23:10:36Z", "by": "2026-10-19T11:46:38Z",
                                         "confirmed": True, "trusted": False}]     # EDDN only: not trusted


def test_state_change_alone_counts_and_rounding_does_not():
    rows = [_r("2026-10-14T20:00:00Z", 0.5936, pending=EXP), _r("2026-10-15T20:00:00Z", 0.59362, active=EXP,
                                                                source="journal")]
    assert infer_system_ticks(rows)[0]["confirmed"]                                     # pending -> active, own journal
    assert infer_system_ticks([_r("2026-10-14T20:00:00Z", 0.5936), _r("2026-10-15T20:00:00Z", 0.59362)]) == []


def test_unconfirmed_stale_upload_is_not_used():
    """An EDDN reading with old values after new ones (EDCAS warns of these) isn't
    confirmed until a later reading agrees."""
    rows = [_r("2026-10-18T10:00:00Z", 0.60), _r("2026-10-18T20:00:00Z", 0.55), _r("2026-10-19T08:00:00Z", 0.60)]
    assert [t["confirmed"] for t in infer_system_ticks(rows)] == [False, False]


def test_merge_adds_only_ticks_no_global_tick_explains():
    sys_ticks = [{"after": "2026-10-17T10:00:00Z", "by": "2026-10-17T20:00:00Z", "confirmed": True},   # global 16:25 explains
                 {"after": "2026-10-18T23:10:36Z", "by": "2026-10-19T11:46:38Z", "confirmed": True},   # missed by tick.edcd.io
                 {"after": "2026-10-19T12:00:00Z", "by": "2026-10-19T13:00:00Z", "confirmed": False}]
    ticks, added = merge_ticks(["2026-10-17T16:25:36Z"], sys_ticks)
    assert ticks == ["2026-10-17T16:25:36Z", "2026-10-19T11:46:38Z"] and list(added) == ["2026-10-19T11:46:38Z"]


def test_reading_at_an_inferred_tick_is_not_provisional():
    from edc.core.bgs_experiment import build_rows
    effort = lambda s, e: {"tier_score": 0, "bounties": 0, "trade_profit": 0, "exploration": 0, "combat_bonds": 0}
    readings = [("2026-10-18T17:21:00Z", 0.6018, "[]", "[]"), ("2026-10-19T14:39:00Z", 0.6447, "[]", "[]")]
    inferred = {"2026-10-19T14:39:00Z": {"after": "2026-10-18T17:21:00Z", "by": "2026-10-19T14:39:00Z"}}
    rows = build_rows(["2026-10-17T16:25:36Z", "2026-10-19T14:39:00Z"], readings, effort,
                      now="2026-10-19T15:00:00Z", inferred=inferred)
    assert not rows[1]["provisional"] and round(rows[1]["change"], 2) == 4.29


def test_missed_tick_seen_in_several_systems_is_promoted(tmp_path):
    from datetime import datetime
    from edc.core.system_ticks import promote_missed_ticks, tick_label
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-17T16:25:36Z")
    # the real 10-18 case: four systems changed between their 10-18 and 10-19 readings
    for addr, (old_at, old, new_at, new) in {
            1: ("2026-10-18T20:21:10Z", 0.5932, "2026-10-19T14:43:13Z", 0.6062),
            2: ("2026-10-18T08:38:25Z", 0.5986, "2026-10-19T14:33:43Z", 0.6060),
            3: ("2026-10-18T17:21:08Z", 0.6018, "2026-10-19T14:39:05Z", 0.6447),
            4: ("2026-10-18T23:10:36Z", 0.7812, "2026-10-19T14:29:15Z", 0.7832)}.items():
        for at, inf in ((old_at, old), (new_at, new)):
            repo.save_faction_snapshot(addr, {"Name": "EUW", "Influence": inf}, at[:10], True, at, "journal")
    assert promote_missed_ticks(repo, now=datetime(2026, 10, 19, 15, 0)) == ("2026-10-18T23:10:36Z", "2026-10-19T14:29:15Z")
    info = repo.get_tick_info(1)[0]
    assert info["source"] == "systems" and "between 10-18 23:10 and 10-19 14:29" in tick_label(info)
    assert promote_missed_ticks(repo, now=datetime(2026, 10, 19, 15, 10)) is None          # now explained
    repo.record_bgs_tick("2026-10-19T02:15:00+00:00")                                      # tick.edcd.io catches up
    assert repo.get_tick_info(1)[0] == {"at": "2026-10-19T02:15:00Z", "source": "edcd", "upper": None}
    db.close()


def test_previous_window_and_dialogs(tmp_path):
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QApplication
    from edc.core.system_ticks import tick_window
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-17T16:25:36Z")
    repo.record_bgs_tick("2026-10-18T23:10:36Z", source="systems", upper="2026-10-19T14:29:15Z")
    repo.save_system_name_if_missing(42, "ICZ XZ-P b5-1")
    repo.record_faction_bounty(system_address=42, faction_name="EUW", amount=11_035_678, redeemed_at="2026-10-18T10:00:00Z")
    prev = tick_window(repo, "previous")
    assert (prev["since"], prev["until"]) == ("2026-10-17T16:25:36Z", "2026-10-18T23:10:36Z")
    assert "between 10-18 23:10 and 10-19 14:29" in tick_window(repo, "current")["text"]
    report = repo.get_session_activity_report(prev["since"], prev["until"])
    assert report["2026-10-18"]["ICZ XZ-P b5-1"]["EUW"]["bounties_total"] == 11_035_678
    assert repo.get_session_activity_report("2026-10-18T23:10:36Z") == {}              # current window: fresh
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name="EUW", _latest_known_tick=None))
    dlg.refresh()
    assert dlg._report == {} and "between 10-18 23:10" in dlg._tick_label.text()
    dlg._window_combo.setCurrentIndex(1)                                                  # Previous tick
    assert dlg._report["2026-10-18"]["ICZ XZ-P b5-1"]["EUW"]["bounties_total"] == 11_035_678
    assert dlg._tick_label.text().startswith("Previous tick window: 10-17 16:25 → 10-18 23:10 UTC")
    db.close()


def test_eddn_only_changes_never_promote_a_tick(tmp_path):
    """EDDN is unauthenticated: at least one trusted reading (journal or EDSM) must show the change."""
    from datetime import datetime
    from edc.core.system_ticks import promote_missed_ticks
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-17T16:25:36Z")
    for addr in (1, 2, 3):
        for at, inf in (("2026-10-18T20:00:00Z", 0.50), ("2026-10-19T10:00:00Z", 0.55), ("2026-10-19T12:00:00Z", 0.55)):
            repo.save_faction_snapshot(addr, {"Name": "EUW", "Influence": inf}, at[:10] + at[11:13], True, at, "eddn")
    assert promote_missed_ticks(repo, now=datetime(2026, 10, 19, 15, 0)) is None
    db.close()


def test_single_edsm_reading_per_system_promotes_when_three_overlap(tmp_path):
    """10-20/10-21: most systems are read once a day, so waiting for a second
    reading to agree held real ticks back. Three overlapping systems now do;
    two don't."""
    from datetime import datetime
    from edc.core.system_ticks import promote_missed_ticks
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-19T16:26:44Z", source="eddn")
    windows = {1: ("2026-10-20T16:36:00Z", "2026-10-21T09:56:00Z"),     # ICZ RD-T c3-16
               2: ("2026-10-20T16:45:00Z", "2026-10-21T10:42:00Z"),     # HIP 114880
               3: ("2026-10-20T15:24:00Z", "2026-10-21T15:48:00Z")}     # ICZ RY-R b4-2
    for addr, (old_at, new_at) in list(windows.items())[:2]:
        for at, inf in ((old_at, 0.30), (new_at, 0.32)):
            repo.save_faction_snapshot(addr, {"Name": "F", "Influence": inf}, at[:10], True, at, "edsm")
    now = datetime(2026, 10, 21, 16, 0)
    assert promote_missed_ticks(repo, now=now) is None                       # two systems: not enough
    old_at, new_at = windows[3]
    for at, inf in ((old_at, 0.30), (new_at, 0.32)):
        repo.save_faction_snapshot(3, {"Name": "F", "Influence": inf}, at[:10], True, at, "edsm")
    assert promote_missed_ticks(repo, now=now) == ("2026-10-20T16:45:00Z", "2026-10-21T09:56:00Z")
    db.close()


def test_missed_tick_found_by_sampling_systems_after_the_app_was_closed(tmp_path):
    """No tick known for 20+ h: a few systems read from EDSM right away bracket
    the tick with their readings from before the gap; then not again for 2 h."""
    from datetime import datetime, timezone
    from edc.core import system_ticks
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-19T16:26:44Z", source="eddn")
    for addr in (1, 2, 3, 4):
        repo.save_system_name_if_missing(addr, f"S{addr}")
        repo.save_faction_snapshot(addr, {"Name": "F", "Influence": 0.30}, "2026-10-20", True,
                                   f"2026-10-20T1{addr}:00:00Z", "edsm")
    repo.save_faction_snapshot(4, {"Name": "F", "Influence": 0.30}, "2026-10-21", True,
                               "2026-10-21T17:00:00Z", "edsm")              # read 1 h ago: not sampled
    asked = []

    def fetch(name):
        asked.append(name)
        return {"system_address": int(name[1:]), "factions": [
            {"Name": "F", "Influence": 0.33, "is_controlling": True, "LastUpdate": "2026-10-21T12:00:00Z"}]}, None
    now = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
    system_ticks._last_sample = None
    assert system_ticks.sample_for_missed_tick(repo, fetch, now) == 3 and sorted(asked) == ["S1", "S2", "S3"]
    assert system_ticks.promote_missed_ticks(repo, now) == ("2026-10-20T13:00:00Z", "2026-10-21T12:00:00Z")
    system_ticks._last_sample = None
    assert system_ticks.sample_for_missed_tick(repo, fetch, now) == 0       # the promoted tick ended 6 h ago
    db.close()


def test_a_tick_explains_only_one_change_per_system():
    """ICZ RY-R b4-2: changed by 10-21 15:48 (the 10-21 03:49 tick), then again
    by 10-22 13:14. The 15:48 reading is 12 h after 03:49, but RY-R had already
    updated for it, so the second change is a new tick."""
    from edc.core.system_ticks import merge_ticks
    ticks = ["2026-10-21T03:49:58Z"]
    changes = [{"after": "2026-10-20T15:24:15Z", "by": "2026-10-21T15:48:44Z", "confirmed": True},
               {"after": "2026-10-21T15:48:44Z", "by": "2026-10-22T13:14:29Z", "confirmed": True}]
    _all, added = merge_ticks(ticks, changes)
    assert list(added) == ["2026-10-22T13:14:29Z"]
    _all, added = merge_ticks(ticks, changes[1:])          # no earlier change seen: could be late propagation
    assert added == {}


def test_older_tick_windows_and_a_reading_two_ticks_later():
    """VE-Q: 18M bounties on 10-20, next read 10-22 after two ticks. Session
    Activity can go 2 windows back; the Experiment Log shows the later reading
    as a combined change, not as that window's result."""
    from edc.core.bgs_experiment import build_rows
    from edc.core.system_ticks import tick_window
    from edc.ui.panels.bgs_experiment_dialog import row_cells
    from types import SimpleNamespace
    ticks = ["2026-10-20T11:33:01Z", "2026-10-21T03:49:58Z", "2026-10-21T15:51:28Z"]
    repo = SimpleNamespace(get_tick_info=lambda n: [{"at": t, "source": "eddn", "upper": None}
                                                    for t in reversed(ticks)][:n])
    w = tick_window(repo, 2)
    assert (w["since"], w["until"]) == ("2026-10-20T11:33:01Z", "2026-10-21T03:49:58Z")
    assert w["text"].startswith("Tick window 2 back: 10-20 11:33 → 10-21 03:49 UTC")
    assert tick_window(repo, 5)["until"] is None                   # not that many ticks: current
    effort = {"tier_score": 0, "bounties": 0, "trade_profit": 0, "exploration": 0}
    rows = build_rows(ticks, [("2026-10-20T18:03:12Z", 0.6060, None, None), ("2026-10-22T13:10:36Z", 0.6438, None, None)],
                      lambda s, e: effort, now="2026-10-22T16:00:00Z")
    bounty_row = rows[-1]
    assert bounty_row["change"] is None and bounty_row["late_after"][1] == 2
    assert "60.60% → 64.38% after 2 ticks (+3.78 combined)" in row_cells(bounty_row)[6]


def test_readings_from_before_and_after_a_mid_day_tick_are_both_kept(tmp_path):
    """faction_snapshots keeps one row a day, so a morning reading was overwritten
    by the evening one and the tick between them couldn't be seen (2026-10-22)."""
    from edc.core.system_ticks import infer_system_ticks
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    for at, inf in (("2026-10-22T13:06:42Z", 0.6447), ("2026-10-22T20:00:00Z", 0.6560)):
        repo.save_faction_snapshot(42, {"Name": "EUW", "Influence": inf}, "2026-10-22", True, at, "journal")
    assert db.conn.execute("SELECT COUNT(*) FROM faction_snapshots").fetchone()[0] == 1   # one per day, as before
    assert [r[0] for r in repo.get_system_readings(42)] == ["2026-10-22T13:06:42Z", "2026-10-22T20:00:00Z"]
    assert [(t["after"], t["by"]) for t in infer_system_ticks(repo.get_system_readings(42))] == [
        ("2026-10-22T13:06:42Z", "2026-10-22T20:00:00Z")]
    assert [r[1] for r in repo.get_influence_readings(42, "EUW")] == [0.6447, 0.6560]
    assert repo.get_recently_read_systems("2026-10-22T00:00:00Z") == [42]
    db.close()


def test_a_tick_after_a_recorded_range_is_a_new_tick(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-21T15:51:28Z", source="systems", upper="2026-10-22T13:06:42Z")
    repo.record_bgs_tick("2026-10-22T17:11:37Z", source="eddn")         # 4 h after the range ended
    repo.record_bgs_tick("2026-10-22T12:00:00Z", source="eddn")         # inside the range: the same tick
    repo.record_bgs_tick("2026-10-22T19:00:00Z", source="eddn")         # 2 h after 17:11: the same tick
    assert [t["at"] for t in repo.get_tick_info(5)] == ["2026-10-22T17:11:37Z", "2026-10-21T15:51:28Z"]
    db.close()
