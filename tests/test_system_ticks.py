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
                                         "confirmed": True}]


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
