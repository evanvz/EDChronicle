"""edc/core/bgs_tasks.py -- per-task progress/status for the BGS Tasks
tracker, from data the app already stores. Pure functions; fake inputs in
the exact shapes the Repository returns."""
from types import SimpleNamespace

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, STATUS_DONE, STATUS_ENDED, STATUS_LOSING, STATUS_NO_DATA, STATUS_TODO, STATUS_TRACKING,
    bgs_limits, build_task_view, build_task_views, faction_activity, find_conflict, hud_line,
    task_title, validate_task_input,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None, opponent=None, note=None, system="Ekono", address=12345,
          created_at="2026-09-26T00:00:00Z", task_id=1):
    return {"id": task_id, "system_address": address, "system_name": system, "task_type": task_type,
            "faction_name": faction, "opponent_name": opponent, "note": note, "sort_order": 0,
            "created_at": created_at}


def _entry(count=0, weighted=0, bonds=0, bounties=0, cz_space_h=0, profit=0, exploration=0, exobiology=0):
    return {
        "missions": {"count": count, "weighted": weighted, "primary_count": count, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": bonds, "bounties_total": bounties,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": cz_space_h},
        "trade_sold": {"commodity": profit, "exploration": exploration, "exobiology": exobiology},
    }


def _conflict(war_type, f1, d1, f2, d2, status="active"):
    return {"faction1": f1, "faction2": f2, "war_type": war_type, "status": status,
            "won_days1": d1, "won_days2": d2, "stake1": None, "stake2": None}


# --- small helpers ---

def test_bgs_limits_reads_cfg():
    cfg = SimpleNamespace(bgs_limit_tier_score=30, bgs_limit_bounties_cr=10_000_000, bgs_limit_exploration_cr=5_000_000)
    assert bgs_limits(cfg) == {"tier_score": 30, "bounties": 10_000_000, "exploration": 5_000_000,
                               "by_population": True}


def test_validate_task_input():
    assert validate_task_input("Ekono", "boost", "EUW", "", "") == ""
    assert validate_task_input("", "boost", "EUW", "", "") == "Enter a system name."
    assert validate_task_input("Ekono", "boost", "", "", "") == "Enter the faction to support."
    assert validate_task_input("Ekono", "vote", "A", "", "") == "Enter the opposing faction."
    assert validate_task_input("Ekono", "fight", "A", "B", "") == ""
    assert validate_task_input("", "note", "", "", "") == "Enter the note text."
    assert validate_task_input("", "note", "", "", "watch Andel") == ""
    assert validate_task_input("Ekono", "powerplay", "", "", "") == ""


def test_task_title():
    assert task_title(_task("boost", "Elite United Worlds")) == "Ekono — Boost Elite United Worlds"
    assert task_title(_task("vote", "A", "B", system="Kanuket")) == "Kanuket — Vote A vs B"
    assert task_title(_task("note", note="x", system="")) == "Note"


def test_faction_activity_sums_across_days_case_insensitively():
    report = {
        "2026-09-25": {"Ekono": {"Elite United Worlds": _entry(count=2, weighted=5, bounties=1_000)}},
        "2026-09-26": {"EKONO": {"elite united worlds": _entry(count=1, weighted=-1, cz_space_h=2, profit=600_000)}},
    }
    act = faction_activity(report, "ekono", "Elite United Worlds")
    assert act == {"missions": 3, "tier_score": 4, "bounties": 1_000, "combat_bonds": 0, "cz_kills": 2, "cz_value": 3.2,
                   "trade_profit": 600_000, "trade_bought": 0, "exploration": 0, "exobiology": 0}


def test_find_conflict_orients_to_our_faction():
    status = {"conflicts": [_conflict("election", "B", 2, "A", 0)], "faction_states": [], "data_timestamp": "x"}
    c = find_conflict(status, "A", "B", ("election",))
    assert c["days_for"] == 0 and c["days_against"] == 2
    assert find_conflict(status, "A", "B", ("war", "civilwar")) is None
    assert find_conflict(None, "A", "B", ("election",)) is None


# --- Boost ---

def test_boost_todo_with_progress_lines():
    report = {"2026-09-26": {"Ekono": {"EUW": _entry(count=3, weighted=12, bounties=5_000_000, profit=3_400_000)}}}
    history = [
        {"faction_name": "EUW", "snapshot_date": "2026-09-26", "influence": 0.42},
        {"faction_name": "EUW", "snapshot_date": "2026-09-25", "influence": 0.412},
    ]
    view = build_task_view(_task("boost", "EUW"), report, None, history, None, LIMITS)
    assert view["status"] == STATUS_TODO
    assert view["lines"] == [
        "Tier score 12 / 25 (3 missions)",
        "Bounties 5.0M / 20.0M",
        "Exploration 0 / 20.0M",
        "Trade profit 3.4M",
        "Influence 41.2% → 42.0% (as of 2026-09-26)",
    ]
    assert view["warnings"] == []
    assert view["hud"] == "Boost EUW — tier score 12/25"


def test_boost_done_when_a_stream_reaches_its_limit_and_warns_past_it():
    report = {"2026-09-26": {"Ekono": {"EUW": _entry(count=6, weighted=27)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["warnings"] == ["Tier score past the daily target — diminishing returns"]


def test_boost_losing_ground_when_influence_dropped():
    history = [
        {"faction_name": "EUW", "snapshot_date": "2026-09-26", "influence": 0.40},
        {"faction_name": "EUW", "snapshot_date": "2026-09-25", "influence": 0.41},
    ]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS)
    assert view["status"] == STATUS_LOSING


# --- Vote ---

def _status(*conflicts, ts="2026-09-26T12:00:00Z"):
    return {"conflicts": list(conflicts), "faction_states": [], "data_timestamp": ts}


def test_vote_shows_score_and_counts_non_combat_actions():
    report = {"2026-09-26": {"Kanuket": {"A": _entry(count=2, weighted=4, profit=1_200_000)}}}
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), report,
                           _status(_conflict("election", "A", 2, "B", 0)), [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["lines"][0] == "Days won 2 - 0 (active)"
    assert view["lines"][1] == "Your actions: 2 missions (tier score 4), trade profit 1.2M, exploration 0"
    assert view["hud"] == "Vote A vs B — 2-0"
    assert view["updated_at"] == "2026-09-26T12:00:00Z"


def test_vote_warns_that_combat_does_not_count():
    report = {"2026-09-26": {"Kanuket": {"A": _entry(bonds=50_000)}}}
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), report,
                           _status(_conflict("election", "A", 0, "B", 0)), [], None, LIMITS)
    assert "Combat doesn't count in elections" in view["warnings"]
    assert view["status"] == STATUS_TODO


def test_vote_losing_ground():
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), {},
                           _status(_conflict("election", "A", 0, "B", 2)), [], None, LIMITS)
    assert view["status"] == STATUS_LOSING


def test_vote_no_data_when_status_older_than_task():
    view = build_task_view(_task("vote", "A", "B", created_at="2026-09-26T13:00:00Z"), {},
                           _status(ts="2026-09-26T12:00:00Z"), [], None, LIMITS)
    assert view["status"] == STATUS_NO_DATA
    assert view["hud"] == "Vote A vs B — no score yet"


def test_vote_ended_when_read_since_task_created_and_gone():
    view = build_task_view(_task("vote", "A", "B", created_at="2026-09-26T11:00:00Z"), {},
                           _status(ts="2026-09-26T12:00:00Z"), [], None, LIMITS)
    assert view["status"] == STATUS_ENDED


# --- Fight ---

def test_fight_unknown_won_days_show_as_question_marks_and_are_never_losing():
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ"), {},
                           _status(_conflict("civilwar", "Damona", None, "UID", None)), [], None, LIMITS)
    assert view["lines"][0] == "Days won ? - ? (active)"
    assert view["hud"].endswith("— ?-?")
    assert view["status"] == STATUS_TODO


def test_fight_losing_ground_when_opponent_has_more_won_days_and_no_actions():
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ"), {},
                           _status(_conflict("civilwar", "UID", 0, "Damona", 3)), [], None, LIMITS)
    assert view["status"] == STATUS_LOSING


def test_fight_ended_when_status_read_after_task_created_and_conflict_gone():
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ", created_at="2026-09-26T11:00:00Z"), {},
                           _status(ts="2026-09-26T12:00:00Z"), [], None, LIMITS)
    assert view["status"] == STATUS_ENDED


def test_fight_todo_when_zero_zero_and_no_actions():
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ"), {},
                           _status(_conflict("civilwar", "UID", 0, "Damona", 0)), [], None, LIMITS)
    assert view["status"] == STATUS_TODO


def test_fight_counts_combat_actions_and_warns_about_bonds_for_opponent():
    report = {"2026-09-26": {"ICZ": {
        "UID": _entry(cz_space_h=1),
        "Damona": _entry(bonds=80_000),
    }}}
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ"), report,
                           _status(_conflict("civilwar", "Damona", 0, "UID", 0)), [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["lines"][0] == "Days won 0 - 0 (active)"
    assert view["lines"][1] == "Your actions: 1 CZ fought (worth 1.6 low space CZs), combat bonds 0, 0 missions"
    assert view["warnings"] == ["You cashed combat bonds for Damona"]


# --- PowerPlay / Note ---

def test_powerplay_view():
    pp = {"pp_state": "Unoccupied", "pp_control_progress": 0.789, "pp_controlling_power": None,
          "pp_data_timestamp": "2026-09-26T10:00:00Z"}
    view = build_task_view(_task("powerplay", note="acquisition"), {}, None, [], pp, LIMITS)
    assert view["status"] == STATUS_TRACKING
    assert view["lines"] == ["Unoccupied (no power yet) — 78.9%", "acquisition"]
    assert view["hud"] == "PowerPlay — Unoccupied (no power yet) — 78.9%"
    assert view["updated_at"] == "2026-09-26T10:00:00Z"


def test_powerplay_without_reading():
    view = build_task_view(_task("powerplay"), {}, None, [], None, LIMITS)
    assert view["status"] == STATUS_NO_DATA
    assert view["lines"] == ["No PowerPlay reading yet"]


def test_note_view():
    view = build_task_view(_task("note", note="Undermine in Andel", system=""), {}, None, [], None, LIMITS)
    assert view["status"] == ""
    assert view["lines"] == ["Undermine in Andel"]
    assert view["hud"] == "Note: Undermine in Andel"


# --- HUD line and repo-driven builder ---

def test_hud_line_joins_views():
    assert hud_line([]) == ""
    assert hud_line([{"hud": "Boost A — tier score 1/25"}, {"hud": "Note: x"}]) == \
        "Squadron task: Boost A — tier score 1/25 · Note: x"


def test_build_task_views_filters_by_system_and_uses_repo():
    tasks = [_task("boost", "EUW", address=12345, task_id=1), _task("note", note="x", address=None, system="", task_id=2)]
    calls = []
    repo = SimpleNamespace(
        list_bgs_tasks=lambda: tasks,
        get_session_activity_report=lambda since: calls.append(since) or {},
        get_bgs_status_for_system=lambda addr: None,
        get_faction_history=lambda addr: [],
        get_system_powerplay_snapshot=lambda addr: None,
        get_system_population=lambda addr: None,
    )
    views = build_task_views(repo, "2026-09-26T00:00:00Z", LIMITS, system_address=12345)
    assert [v["task"]["id"] for v in views] == [1]
    assert calls == ["2026-09-26T00:00:00Z"]
    assert build_task_views(repo, "t", LIMITS, system_address=999) == []
