"""Acquisition progress: newest of our journal or EDDN, a "to go" line, and
recovery of progress for visits saved before it was kept."""
import json
from datetime import datetime, timedelta, timezone

from edc.core.bgs_tasks import DEFAULT_LIMITS, build_task_view
from edc.core.eddn_powerplay import EddnPowerPlayCache
from edc.core.powerplay_pledge_scanner import scan_conflict_progress
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

LIMITS = dict(DEFAULT_LIMITS)


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task():
    return {"id": 1, "system_address": 7, "system_name": "Tucanae", "task_type": "powerplay", "faction_name": None,
            "opponent_name": None, "note": None, "sort_order": 0, "created_at": "x", "pp_mode": None}


_PP = {"pp_state": "Unoccupied", "pp_powers": ["Aisling Duval"], "pp_control_progress": None,
       "pp_controlling_power": None, "pp_conflict_progress": {"Aisling Duval": 0.804}, "pp_data_timestamp": _iso(120)}


def test_newer_eddn_progress_wins_and_shows_what_is_left():
    eddn = {"progress": {"Aisling Duval": 0.825}, "date": _iso(2)}
    view = build_task_view(_task(), {}, None, [], _PP, LIMITS, pledged="Aisling Duval", eddn_progress=eddn)
    assert view["lines"][0] == "Acquisition: Unoccupied (no power yet) — Aisling Duval 82.5% (EDDN, 2h ago)"
    assert view["lines"][1] == "17.5% to go before Thursday's cycle (100% = Aisling Duval takes the system)"


def test_older_eddn_progress_does_not_replace_our_visit():
    eddn = {"progress": {"Aisling Duval": 0.5}, "date": _iso(500)}
    view = build_task_view(_task(), {}, None, [], _PP, LIMITS, pledged="Aisling Duval", eddn_progress=eddn)
    assert view["lines"][0].endswith("Aisling Duval 80.4%")


def test_threshold_reached_and_contested_wording():
    pp = dict(_PP, pp_conflict_progress={"Aisling Duval": 1.02, "Zachary Hudson": 1.1})
    view = build_task_view(_task(), {}, None, [], pp, LIMITS, pledged="Aisling Duval")
    assert "unless it's Contested (Zachary Hudson also reached it)" in view["lines"][1]


def test_eddn_cache_keeps_newest_progress_and_persists(tmp_path):
    cache = EddnPowerPlayCache(tmp_path)
    cache.ingest_conflict_progress(7, {"Aisling Duval": 0.82}, "2026-10-02T10:00:00Z")
    cache.ingest_conflict_progress(7, {"Aisling Duval": 0.70}, "2026-10-01T10:00:00Z")  # older, ignored
    cache.save()
    assert EddnPowerPlayCache(tmp_path).get_conflict_progress(7) == {"progress": {"Aisling Duval": 0.82},
                                                                     "date": "2026-10-02T10:00:00Z"}


def test_backfill_recovers_missing_progress_for_that_visit_only(tmp_path):
    (tmp_path / "j").mkdir()
    (tmp_path / "j" / "Journal.2026-09-26T200000.01.log").write_text(json.dumps({
        "event": "FSDJump", "timestamp": "2026-09-26T21:51:42Z", "SystemAddress": 7,
        "PowerplayConflictProgress": [{"Power": "Aisling Duval", "ConflictProgress": 0.804092}]}), encoding="utf-8")
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.save_system_powerplay_snapshot(
        system_address=7, system_name="Tucanae", pp_state="Unoccupied", control_progress=None, reinforcement=None,
        undermining=None, controlling_power=None, powers=["Aisling Duval"], data_timestamp="2026-09-26T21:51:42Z")
    assert repo.backfill_conflict_progress(scan_conflict_progress(tmp_path / "j")) == 1
    assert repo.get_system_powerplay_snapshot(7)["pp_conflict_progress"] == {"Aisling Duval": 0.804092}
    assert repo.backfill_conflict_progress(scan_conflict_progress(tmp_path / "j")) == 0  # already filled
