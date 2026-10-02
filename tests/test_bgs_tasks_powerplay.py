"""BGS Tasks tracker: PowerPlay mode (reinforcement / acquisition /
undermining) worked out from the pledged power, merits earned in the task's
system this PowerPlay week, and a short "what to do" line on every card."""
from datetime import datetime, timezone
from types import SimpleNamespace

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, build_task_view, build_task_views, powerplay_mode, powerplay_week_start,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None, opponent=None, note=None, address=12345, task_id=1):
    return {"id": task_id, "system_address": address, "system_name": "Tucanae", "task_type": task_type,
            "faction_name": faction, "opponent_name": opponent, "note": note, "sort_order": 0,
            "created_at": "2026-09-26T00:00:00Z"}


def _act(action, bonus=(), merits="yes", bgs="safe"):
    return SimpleNamespace(action=action, bonus_powers=list(bonus), merits=merits, bgs=bgs)


class _Table:
    def __init__(self, acts):
        self.acts = acts
        self.calls = []

    def get_actions(self, system_type, pp_state=""):
        self.calls.append((system_type, pp_state))
        return self.acts


# --- PowerPlay week start (Thursday ~07:00 UTC, same estimate as the Faction Expansion Tracker) ---

def test_week_start_is_the_most_recent_thursday_0700_utc():
    # Saturday 2026-09-26 18:00 UTC -> Thursday 2026-09-24 07:00 UTC
    assert powerplay_week_start(datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)) == "2026-09-24T07:00:00Z"


def test_week_start_on_thursday_before_and_after_0700():
    assert powerplay_week_start(datetime(2026, 9, 24, 6, 59, tzinfo=timezone.utc)) == "2026-09-17T07:00:00Z"
    assert powerplay_week_start(datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)) == "2026-09-24T07:00:00Z"


# --- mode ---

def test_powerplay_mode_rules():
    assert powerplay_mode("Aisling Duval", "Aisling Duval", "Fortified") == "Reinforcement"
    assert powerplay_mode("Aisling Duval", "aisling duval", "Exploited") == "Reinforcement"
    assert powerplay_mode("Aisling Duval", "Zachary Hudson", "Stronghold") == "Undermining"
    assert powerplay_mode("Aisling Duval", "", "Unoccupied") == "Acquisition"
    assert powerplay_mode("Aisling Duval", "", "") == ""
    assert powerplay_mode("", "Zachary Hudson", "Stronghold") == ""


# --- PowerPlay card ---

_PP = {"pp_state": "Unoccupied", "pp_control_progress": 0.789, "pp_controlling_power": None,
       "pp_data_timestamp": "2026-09-26T10:00:00Z"}


def test_pledged_card_shows_mode_merits_and_top_activities_bonus_first():
    table = _Table([
        _act("Bounty Hunting"), _act("Power Kills"), _act("Suspended Thing", merits="suspended"),
        _act("Transport Powerplay Commodities", bonus=["Aisling Duval"]), _act("Holoscreen Hacking"),
        _act("Sell Rare Goods"),
    ])
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS,
                           pledged="Aisling Duval", merits=340, pp_activities=table)
    assert view["lines"][0] == "Acquisition: Unoccupied (no power yet) — 78.9%"
    assert "Your merits here this PowerPlay week: 340" in view["lines"]
    assert view["hud"] == "PowerPlay — Acquisition: Unoccupied (no power yet) — 78.9% · 340 merits this week"
    assert view["guide"] == ("Acquisition — BGS-safe: Transport Powerplay Commodities, "
                             "Bounty Hunting (cash vouchers elsewhere), Power Kills, Holoscreen Hacking")
    assert table.calls == [("acquisition", "Unoccupied")]


def test_pledged_card_in_a_system_not_targetable():
    view = build_task_view(_task("powerplay"), {}, None, [],
                           dict(_PP, pp_state="", pp_control_progress=None), LIMITS,
                           pledged="Aisling Duval", merits=0, pp_activities=None)
    assert view["guide"] == "Not a PowerPlay target for your power right now"


def test_unpledged_card_says_to_pledge():
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS)
    assert view["guide"] == "Pledge to a power to see PowerPlay actions for this system"
    assert not any("merits" in line for line in view["lines"])


# --- guidance on the BGS cards ---

def test_boost_vote_fight_have_guidance_naming_the_factions():
    boost = build_task_view(_task("boost", "EUW"), {}, None, [], None, LIMITS)
    assert "EUW" in boost["guide"] and "25 INF+" in boost["guide"]
    vote = build_task_view(_task("vote", "A", "B"), {}, None, [], None, LIMITS)
    assert "Combat doesn't count" in vote["guide"]
    fight = build_task_view(_task("fight", "A", "B"), {}, None, [], None, LIMITS)
    assert "conflict zones for A" in fight["guide"] and "Don't cash bonds for B" in fight["guide"]
    note = build_task_view(_task("note", note="x"), {}, None, [], None, LIMITS)
    assert note["guide"] == ""


# --- builder fetches merits since the week start ---

def test_build_task_views_queries_merits_since_week_start():
    calls = []
    repo = SimpleNamespace(
        list_bgs_tasks=lambda: [_task("powerplay")],
        get_session_activity_report=lambda since: {},
        get_bgs_status_for_system=lambda addr: None,
        get_faction_history=lambda addr: [],
        get_system_powerplay_snapshot=lambda addr: _PP,
        get_powerplay_merits_since=lambda addr, since: calls.append((addr, since)) or 55,
        get_system_population=lambda addr: 51_900_000,
    )
    now = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    views = build_task_views(repo, "t", LIMITS, pledged="Aisling Duval", now=now)
    assert calls == [(12345, "2026-09-24T07:00:00Z")]
    assert "Your merits here this PowerPlay week: 55" in views[0]["lines"]
    assert "Population: 51.9 million (large)" in views[0]["lines"]


def test_population_text():
    from edc.core.bgs_tasks import population_text
    assert population_text(51_900_000) == "51.9 million (large)"
    assert population_text(850_000) == "850k (small)"
    assert population_text(3_200_000_000) == "3.2 billion (large)"
    assert population_text(None) == "unknown"


# --- per-line target state on Boost cards ---

def _entry(count=0, weighted=0, bounties=0, exploration=0):
    return {
        "missions": {"count": count, "weighted": weighted, "primary_count": count, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": 0, "bounties_total": bounties,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
        "trade_sold": {"commodity": 0, "exploration": exploration, "exobiology": 0},
    }


def test_boost_line_states_under_met_and_over():
    report = {"2026-09-26": {"Tucanae": {"EUW": _entry(count=5, weighted=25, bounties=21_000_000, exploration=1)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["line_states"][:3] == ["met", "over", ""]
    assert view["lines"][0] == "Tier score 25 / 25 (5 missions) ✓"
    assert view["lines"][1] == "Bounties 21.0M / 20.0M ✓"
    assert view["lines"][2] == "Exploration 1 / 20.0M"
    assert len(view["line_states"]) == len(view["lines"])


def test_non_boost_line_states_are_blank_and_aligned():
    view = build_task_view(_task("vote", "A", "B", note="x"), {}, None, [], None, LIMITS)
    assert view["line_states"] == [""] * len(view["lines"])


def test_single_mission_is_singular():
    report = {"2026-09-26": {"Tucanae": {"EUW": _entry(count=1, weighted=3)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["lines"][0] == "Tier score 3 / 25 (1 mission)"


# --- BGS-safe first; joint BGS/PP actions only when also boosting ---

def test_guide_lists_bgs_safe_first_and_flags_joint_actions():
    table = _Table([_act("Sell for Large Profits", bonus=["Aisling Duval"], bgs="joint"),
                    _act("Scan Datalinks"), _act("Sell Rare Goods", bgs="joint")])
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS, pledged="Aisling Duval", pp_activities=table)
    assert view["guide"] == ("Acquisition — BGS-safe: Scan Datalinks. Only if also boosting the station's "
                             "faction: Sell for Large Profits, Sell Rare Goods")


# --- ZYADA allies: never Undermining ---

def test_allied_power_system_is_never_undermining():
    from edc.core.bgs_tasks import allied_powers
    allies = allied_powers("Aisling Duval")
    assert allies == {"zemina torval", "yuri grom", "a. lavigny-duval", "denton patreus"}
    # The game writes Arissa as "A. Lavigny-Duval"; both spellings must match.
    assert powerplay_mode("Aisling Duval", "A. Lavigny-Duval", "Fortified", allies=allies) == "Allied"
    assert powerplay_mode("Aisling Duval", "Denton Patreus", "Fortified", allies=allies) == "Allied"
    assert powerplay_mode("Aisling Duval", "Zachary Hudson", "Fortified", allies=allies) == "Undermining"


def test_allies_default_only_for_zyada_pledges_and_config_overrides():
    from edc.core.bgs_tasks import allied_powers
    assert allied_powers("Zachary Hudson") == frozenset()
    assert allied_powers("Aisling Duval", []) == frozenset()
    assert allied_powers("Aisling Duval", ["Li Yong-Rui", "Aisling Duval"]) == {"li yong-rui"}


def test_allied_card_says_do_not_undermine():
    pp = dict(_PP, pp_controlling_power="Arissa Lavigny-Duval", pp_state="Stronghold")
    view = build_task_view(_task("powerplay"), {}, None, [], pp, LIMITS, pledged="Aisling Duval")
    assert view["lines"][0].startswith("Allied:")
    assert view["guide"] == "Allied power's system — don't undermine it (coalition)"
