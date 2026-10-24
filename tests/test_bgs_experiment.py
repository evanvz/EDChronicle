"""BGS Experiment Log: one row per tick window for a test system -- our effort in
the window, the influence level seen during it, the level after the next tick,
the change as a share of headroom, against the 6-8% likely ceiling."""
from edc.core.bgs_experiment import build_rows

TICKS = ["2026-10-17T15:00:00Z", "2026-10-18T15:10:00Z", "2026-10-19T15:05:00Z"]


def _effort(start, end):
    return {("2026-10-17T15:00:00Z"): {"tier_score": 15, "bounties": 10_000_000, "trade_profit": 0,
                                       "exploration": 0, "combat_bonds": 0}}.get(
        start, {"tier_score": 0, "bounties": 0, "trade_profit": 0, "exploration": 0, "combat_bonds": 0})


def test_rows_pair_each_window_with_the_level_after_the_next_tick():
    readings = [
        ("2026-10-17T16:00:00Z", 0.582, '[{"State": "Boom"}]', "[]"),   # seen after tick 1
        ("2026-10-18T16:30:00Z", 0.6052, "[]", "[]"),                    # seen after tick 2
    ]
    rows = build_rows(TICKS, readings, _effort)
    first = rows[-1]                                     # newest first
    assert [first["start"], first["end"]] == TICKS[:2]
    assert (first["before"], first["after"]) == (0.582, 0.6052)
    assert round(first["change"], 2) == 2.32 and round(first["share"], 2) == 5.55
    assert first["effort"]["bounties"] == 10_000_000 and round(first["points"], 2) == round(0.5 * 3.9069 + 1.33 * 4.4739, 2)
    assert first["states"] == "Boom"
    assert [round(x, 2) for x in first["ceiling"]] == [2.51, 3.34]
    assert len(rows) == 3 and rows[0]["end"] is None     # newest window still open
    second = rows[1]                                     # tick 2 -> tick 3: no reading after tick 3 yet
    assert second["before"] == 0.6052 and second["after"] is None and second["change"] is None


def test_open_window_and_missing_readings():
    rows = build_rows(TICKS[:1], [], _effort, now="2026-10-17T18:00:00Z")
    assert len(rows) == 1 and rows[0]["end"] is None and rows[0]["before"] is None   # still running, not visited
    assert build_rows([], [], _effort) == []


def test_tick_worker_records_tick_and_backfills_history(tmp_path):
    from unittest.mock import patch
    from edc.ui.main_window import _BgsTickCheckWorker
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations(); db.close()
    history = ["2026-10-10T16:09:08+00:00", "2026-10-11T15:00:09+00:00"]
    with patch("edc.ui.main_window.fetch_latest_tick", return_value="2026-10-12T16:09:01+00:00"), \
         patch("edc.ui.main_window.fetch_tick_history", return_value=history) as hist:
        w = _BgsTickCheckWorker(str(tmp_path / "t.db"))
        w.run()
        w.run()                                   # same tick again: no second history fetch
    db = Database(tmp_path / "t.db")
    assert Repository(db).get_bgs_ticks() == ["2026-10-10T16:09:08Z", "2026-10-11T15:00:09Z", "2026-10-12T16:09:01Z"]
    assert hist.call_count == 1
    db.close()


def test_dialog_tabs_rows_and_copy(tmp_path):
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QApplication
    from edc.ui.panels.bgs_experiment_dialog import BgsExperimentDialog
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    from datetime import datetime, timedelta, timezone
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    t0 = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    for k in range(2):
        repo.record_bgs_tick(iso(t0 + timedelta(days=k)))
    repo.save_system_name_if_missing(42, "ICZ XZ-P b5-1")
    for day, inf in ((0, 0.582), (1, 0.6052)):
        ts = iso(t0 + timedelta(days=day, hours=1))
        repo.save_faction_snapshot(42, {"Name": "EUW", "Influence": inf}, ts[:10], True, ts, "journal")
    repo.db.execute("INSERT INTO faction_bounties (system_address, faction_name, amount, redeemed_at) VALUES (42, 'EUW', 10000000, ?)",
                    (iso(t0 + timedelta(hours=2)),))
    repo.add_experiment_system("ICZ XZ-P b5-1")
    dlg = BgsExperimentDialog(SimpleNamespace(_repo=repo, _faction_name="EUW"))
    dlg.refresh()
    assert [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())] == ["ICZ XZ-P b5-1", "Systems"]
    table, rows = dlg._tables["ICZ XZ-P b5-1"]
    full = [r for r in rows if r["end"]][0]
    assert full["effort"]["bounties"] == 10_000_000 and round(full["change"], 2) == 2.32
    dlg._copy("ICZ XZ-P b5-1")
    text = QApplication.clipboard().text()
    assert text.startswith("ICZ XZ-P b5-1\n```") and "58.20% → 60.52%" in text and "+2.32" in text


def test_other_visitors_and_other_factions_flag_contamination():
    readings = [("2026-10-17T16:00:00Z", 0.582, "[]", "[]"), ("2026-10-18T16:30:00Z", 0.6052, "[]", "[]")]
    visits = [
        ("2026-10-17T16:00:00Z", "FSDJump", "journal"), ("2026-10-17T16:00:00Z", "FSDJump", "eddn"),  # ours, uploaded
        ("2026-10-17T19:12:00Z", "Docked", "eddn"),                                                     # someone else
        ("2026-10-18T16:40:00Z", "FSDJump", "eddn"),                                                    # next window
    ]
    others = {
        "EUW": [("2026-10-17T16:00:00Z", 0.582), ("2026-10-18T16:30:00Z", 0.6052)],
        "Union Party": [("2026-10-17T16:00:00Z", 0.146), ("2026-10-18T16:30:00Z", 0.151)],   # gained: someone helped it
        "Mafia": [("2026-10-17T16:00:00Z", 0.102), ("2026-10-18T16:30:00Z", 0.097)],
    }
    rows = build_rows(TICKS, readings, _effort, visits=visits, faction_readings=others, faction="EUW")
    first = rows[-1]
    assert first["other_visits"] == 1
    assert first["factions_up"] == ["Union Party"]
    assert first["contaminated"]
    quiet = build_rows(TICKS, readings, _effort, visits=visits[:2], faction_readings={k: v for k, v in others.items()
                                                                                       if k != "Union Party"}, faction="EUW")[-1]
    assert quiet["other_visits"] == 0 and quiet["factions_up"] == [] and not quiet["contaminated"]


def test_listener_reports_visits_only_in_test_systems():
    from edc.core.eddn_listener import EddnPowerPlayWorker
    w = EddnPowerPlayWorker()
    seen = []
    w.system_visit_seen.connect(lambda *a: seen.append(a))
    w.set_experiment_systems({42})
    for msg in ({"SystemAddress": 42, "event": "FSDJump", "timestamp": "2026-10-17T16:00:00Z"},
                {"SystemAddress": 42, "event": "Scan", "timestamp": "2026-10-17T16:01:00Z"},       # not a visit
                {"SystemAddress": 7, "event": "Docked", "timestamp": "2026-10-17T16:02:00Z"}):     # not a test system
        w._maybe_emit_visit(msg)
    assert seen == [(42, "FSDJump", "2026-10-17T16:00:00Z")]


def test_visits_flow_to_table_and_own_visit_recorded(tmp_path):
    from types import SimpleNamespace
    from edc.core.eddn_market import EddnMarketCache, write_buffers
    from edc.ui.main_window import MainWindow
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    cache = EddnMarketCache(repo=None)
    cache.on_system_visit_seen(42, "Docked", "2026-10-17T19:12:00.123Z")
    write_buffers(repo, *cache.pop_buffers())
    fake = SimpleNamespace(repo=repo, _experiment_addresses={42})
    MainWindow._record_own_test_system_visit(fake, {"event": "FSDJump", "SystemAddress": 42,
                                                    "timestamp": "2026-10-17T16:00:00Z"})
    MainWindow._record_own_test_system_visit(fake, {"event": "FSDJump", "SystemAddress": 7,
                                                    "timestamp": "2026-10-17T16:05:00Z"})   # not a test system
    assert repo.get_bgs_visits(42) == [("2026-10-17T16:00:00Z", "FSDJump", "journal"),
                                       ("2026-10-17T19:12:00Z", "Docked", "eddn")]
    assert repo.get_bgs_visits(7) == []


def test_change_during_propagation_is_not_contamination():
    """Real Ekono 2026-10-12/13: 76.36% 5.7 h after the 16:09 tick, 75.35% 20.6 h after.
    A system can take up to 22 h to update after the tick (EDDataHub's measurement),
    so the early reading was the old level, not an unlisted tick."""
    readings = [("2026-10-17T21:49:00Z", 0.7636, "[]", "[]"), ("2026-10-18T14:46:00Z", 0.7535, "[]", "[]")]
    row = build_rows(["2026-10-17T16:09:00Z"], readings, _effort, now="2026-10-18T16:00:00Z")[0]
    assert not row["unlisted_update"] and not row["contaminated"]
    assert row["before"] == 0.7535 and not row["provisional"]          # the settled reading is the baseline


def test_change_after_propagation_is_flagged():
    readings = [("2026-10-18T14:30:00Z", 0.7636, "[]", "[]"), ("2026-10-18T15:40:00Z", 0.7535, "[]", "[]")]
    row = build_rows(["2026-10-17T16:09:00Z"], readings, _effort, now="2026-10-18T16:00:00Z")[0]
    assert row["unlisted_update"] and row["contaminated"]


def test_reading_soon_after_a_tick_is_provisional():
    """VE-Q 2026-10-17: 59.36% two hours after the 16:25 tick, 59.86% next morning."""
    ticks = ["2026-10-16T16:31:00Z", "2026-10-17T16:25:00Z"]
    early = [("2026-10-17T15:00:00Z", 0.5936, "[]", "[]"), ("2026-10-17T18:27:00Z", 0.5936, "[]", "[]")]
    row = build_rows(ticks, early, _effort, now="2026-10-17T19:00:00Z")[-1]
    assert row["provisional"] and row["change"] == 0.0
    later = early + [("2026-10-18T15:06:00Z", 0.5986, "[]", "[]")]           # 22 h+ after the tick
    row = build_rows(ticks, later, _effort, now="2026-10-18T15:30:00Z")[-1]
    assert not row["provisional"] and round(row["change"], 2) == 0.50
