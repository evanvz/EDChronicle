"""BGS Tasks tracker:
- PowerPlay cards show acquisition progress for Unoccupied systems
  (journal PowerplayConflictProgress, e.g. Tucanae Sector DW-V b2-3: Aisling
  Duval 0.804092) and say "Unoccupied (no power yet)" so it isn't read as
  population.
- Boost cards count down a retreat to its Important Day (SINC Complete BGS
  Guide 2024 p56: act on active day 5; the 2.5% check is active day 6)."""
import json
from datetime import date

from edc.core.bgs_tasks import DEFAULT_LIMITS, build_task_view
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None):
    return {"id": 1, "system_address": 12345, "system_name": "Tucanae", "task_type": task_type,
            "faction_name": faction, "opponent_name": None, "note": None, "sort_order": 0,
            "created_at": "2026-09-26T00:00:00Z"}


# --- acquisition progress ---

def test_conflict_progress_round_trips_through_the_snapshot(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.save_system_powerplay_snapshot(
        system_address=1, system_name="Tucanae", pp_state="Unoccupied", control_progress=None,
        reinforcement=None, undermining=None, controlling_power=None, powers=["Aisling Duval"],
        data_timestamp="2026-09-26T21:51:42Z", conflict_progress={"Aisling Duval": 0.804092},
    )
    assert repo.get_system_powerplay_snapshot(1)["pp_conflict_progress"] == {"Aisling Duval": 0.804092}
    repo.save_system_powerplay_snapshot(
        system_address=2, system_name="X", pp_state="Fortified", control_progress=0.5,
        reinforcement=1, undermining=0, controlling_power="Aisling Duval", powers=["Aisling Duval"],
        data_timestamp="2026-09-26T21:51:42Z",
    )
    assert repo.get_system_powerplay_snapshot(2)["pp_conflict_progress"] == {}


_UNOCCUPIED = {"pp_state": "Unoccupied", "pp_control_progress": None, "pp_controlling_power": None,
               "pp_conflict_progress": {"Zachary Hudson": 0.1, "Aisling Duval": 0.804092},
               "pp_data_timestamp": "2026-09-26T21:51:42Z"}


def test_pledged_card_shows_own_power_acquisition_progress():
    view = build_task_view(_task("powerplay"), {}, None, [], _UNOCCUPIED, LIMITS, pledged="Aisling Duval")
    assert view["lines"][0] == "Acquisition: Unoccupied (no power yet) — Aisling Duval 80.4%"


def test_unpledged_card_shows_leading_power_progress():
    view = build_task_view(_task("powerplay"), {}, None, [], _UNOCCUPIED, LIMITS)
    assert view["lines"][0] == "Unoccupied (no power yet) — Aisling Duval 80.4%"


# --- retreat Important Day ---

def _row(day, influence, active=(), pending=()):
    return {"faction_name": "EUW", "snapshot_date": day, "influence": influence,
            "active_states": json.dumps([{"State": s} for s in active]),
            "pending_states": json.dumps([{"State": s} for s in pending])}


def test_active_retreat_counts_down_and_warns_below_threshold():
    history = [  # newest first, as Repository.get_faction_history returns it
        _row("2026-09-22", 0.02, active=["Retreat"]),
        _row("2026-09-21", 0.022, active=["Retreat"]),
        _row("2026-09-20", 0.024, pending=["Retreat"]),
    ]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS, today=date(2026, 9, 22))
    assert ("Retreat active (day 2): Important Day ~2026-09-25 (active day 5), "
            "must be above 2.5% on ~2026-09-26") in view["lines"]
    assert "Influence 2.0% is below 2.5% — the faction retreats unless it's raised" in view["warnings"]


def test_pending_retreat_projects_from_the_next_day():
    history = [_row("2026-09-24", 0.03, pending=["Retreat"])]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS, today=date(2026, 9, 24))
    assert ("Retreat pending: Important Day ~2026-09-29 (active day 5), "
            "must be above 2.5% on ~2026-09-30") in view["lines"]


def test_important_day_today_is_a_warning():
    history = [_row("2026-09-25", 0.03, active=["Retreat"]), _row("2026-09-21", 0.03, active=["Retreat"])]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS, today=date(2026, 9, 25))
    assert "Retreat Important Day is today — hand everything in" in view["warnings"]


def test_no_retreat_no_countdown():
    history = [_row("2026-09-24", 0.4, active=["Boom"])]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS, today=date(2026, 9, 24))
    assert not any(line.startswith("Retreat") for line in view["lines"])
