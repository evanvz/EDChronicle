"""BGS task logic checked against the SINC Complete BGS Guide 2024 (see
memory reference_sinc_bgs_guide_2024): exobiology has no BGS effect,
population-sized daily targets, CZ weights, and advice on what actually
decides war and election days."""
from types import SimpleNamespace

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, STATUS_TODO, build_task_view, build_task_views, population_targets,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None, opponent=None, address=12345, system="Tucanae"):
    return {"id": 1, "system_address": address, "system_name": system, "task_type": task_type,
            "faction_name": faction, "opponent_name": opponent, "note": None, "sort_order": 0,
            "created_at": "2026-09-26T00:00:00Z"}


def _entry(count=0, weighted=0, bounties=0, exploration=0, profit=0, exobiology=0, cz=None, bonds=0):
    cz_kills = {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0}
    cz_kills.update(cz or {})
    return {
        "missions": {"count": count, "weighted": weighted, "primary_count": count, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": bonds, "bounties_total": bounties, "cz_kills": cz_kills,
        "trade_sold": {"commodity": profit, "exploration": exploration, "exobiology": exobiology},
    }


# --- population-sized targets (SINC table, guide p69) ---

def test_population_targets_by_system_size():
    assert population_targets(800_000) == {"tier_score": 15, "bounties": 10_000_000,
                                           "exploration": 5_000_000, "trade_profit": 10_000_000, "size": "small"}
    assert population_targets(1_000_000)["size"] == "medium"
    assert population_targets(25_000_000)["size"] == "medium"
    assert population_targets(51_850_712) == {"tier_score": 50, "bounties": 30_000_000,
                                              "exploration": 15_000_000, "trade_profit": 30_000_000, "size": "large"}
    assert population_targets(None) is None
    assert population_targets(0) is None


def test_boost_card_uses_population_targets_when_given():
    report = {"d": {"Tucanae": {"EUW": _entry(count=3, weighted=12, bounties=5_000_000, profit=3_400_000)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS, population=51_850_712)
    assert view["lines"][:4] == [
        "Tier score 12 / 50 (3 missions)",
        "Bounties 5.0M / 30.0M",
        "Exploration 0 / 15.0M",
        "Trade profit 3.4M / 30.0M",
    ]
    assert "large system" in view["guide"]
    assert "SINC" in view["guide"]
    assert view["hud"] == "Boost EUW — tier score 12/50"


def test_boost_card_falls_back_to_settings_when_population_unknown():
    report = {"d": {"Tucanae": {"EUW": _entry(count=1, weighted=3)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["lines"][0] == "Tier score 3 / 25 (1 mission)"
    assert "Settings" in view["guide"]


def test_population_targets_can_be_switched_off():
    report = {"d": {"Tucanae": {"EUW": _entry(count=1, weighted=3)}}}
    limits = dict(LIMITS, by_population=False)
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, limits, population=51_850_712)
    assert view["lines"][0] == "Tier score 3 / 25 (1 mission)"


def test_builder_reads_population_for_boost_tasks():
    calls = []
    repo = SimpleNamespace(
        list_bgs_tasks=lambda: [_task("boost", "EUW")],
        get_session_activity_report=lambda since: {},
        get_bgs_status_for_system=lambda addr: None,
        get_faction_history=lambda addr: [],
        get_system_powerplay_snapshot=lambda addr: None,
        get_system_population=lambda addr: calls.append(addr) or 800_000,
    )
    views = build_task_views(repo, "t", LIMITS)
    assert calls == [12345]
    assert views[0]["lines"][0] == "Tier score 0 / 15 (0 missions)"


# --- exobiology has no BGS effect (guide p32) ---

def test_exobiology_not_shown_or_counted_on_boost_card():
    report = {"d": {"Tucanae": {"EUW": _entry(exobiology=90_000_000)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert not any("Exobiology" in line for line in view["lines"])


def test_exobiology_alone_does_not_complete_a_vote():
    report = {"d": {"Tucanae": {"A": _entry(exobiology=90_000_000)}}}
    status = {"conflicts": [{"faction1": "A", "faction2": "B", "war_type": "election", "status": "active",
                             "won_days1": 0, "won_days2": 0, "stake1": None, "stake2": None}],
              "faction_states": [], "data_timestamp": "2026-09-26T12:00:00Z"}
    view = build_task_view(_task("vote", "A", "B"), report, status, [], None, LIMITS)
    assert view["status"] == STATUS_TODO


# --- CZ weights (guide p46): space L/M/H 1/1.3/1.6, ground 0.25/0.325/0.4 ---

def test_fight_card_shows_weighted_cz_value():
    report = {"d": {"Tucanae": {"A": _entry(cz={"space_l": 2, "space_h": 1, "ground_h": 1})}}}
    status = {"conflicts": [{"faction1": "A", "faction2": "B", "war_type": "war", "status": "active",
                             "won_days1": 1, "won_days2": 0, "stake1": None, "stake2": None}],
              "faction_states": [], "data_timestamp": "2026-09-26T12:00:00Z"}
    view = build_task_view(_task("fight", "A", "B"), report, status, [], None, LIMITS)
    assert view["lines"][1] == "Your actions: 4 CZs fought (worth 4.0 low space CZs), combat bonds 0, 0 missions"


# --- advice matches what decides each day (guide p44-49) ---

def test_guidance_names_the_deciding_lever():
    fight = build_task_view(_task("fight", "A", "B"), {}, None, [], None, LIMITS)["guide"]
    assert "Win the most conflict zones for A" in fight
    assert "low space CZs" in fight
    assert "only break ties" in fight
    assert "Don't cash bonds for B" in fight
    vote = build_task_view(_task("vote", "A", "B"), {}, None, [], None, LIMITS)["guide"]
    assert "election missions for A" in vote
    assert "only break ties" in vote
    assert "Combat doesn't count" in vote
    boost = build_task_view(_task("boost", "A"), {}, None, [], None, LIMITS)["guide"]
    assert "exobiology and mined goods don't count" in boost


def test_trade_purchases_show_on_boost_and_count_for_votes():
    entry = _entry()
    entry["trade_sold"]["purchase"] = 2_500_000
    report = {"d": {"Tucanae": {"A": entry}}}
    boost = build_task_view(_task("boost", "A"), report, None, [], None, LIMITS)
    assert "Trade buys 2.5M" in boost["lines"]
    status = {"conflicts": [{"faction1": "A", "faction2": "B", "war_type": "election", "status": "active",
                             "won_days1": 0, "won_days2": 0, "stake1": None, "stake2": None}],
              "faction_states": [], "data_timestamp": "2026-09-26T12:00:00Z"}
    vote = build_task_view(_task("vote", "A", "B"), report, status, [], None, LIMITS)
    assert vote["status"] == "Done this tick"
