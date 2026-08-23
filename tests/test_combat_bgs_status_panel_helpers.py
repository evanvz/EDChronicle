"""Tests for the pure formatting/merge helpers in combat_bgs_status_panel.py
-- no Qt needed, these are plain functions over dicts/lists."""
from edc.ui.panels.combat_bgs_status_panel import (
    _merge_results, _conflicts_text, _faction_states_text,
)


# --- _merge_results ---

def test_merge_results_combines_bgs_only_system():
    bgs = [{"system_name": "Sol", "distance_ly": 5.0, "conflicts": [], "faction_states": [], "data_timestamp": "2026-08-23T00:00:00Z"}]
    rows = _merge_results(bgs, [])
    assert rows == [{
        "system_name": "Sol", "distance_ly": 5.0, "conflicts": [], "faction_states": [],
        "tiers": [], "data_timestamp": "2026-08-23T00:00:00Z",
    }]


def test_merge_results_combines_res_only_system():
    res = [{"system_name": "Sol", "distance_ly": 5.0, "tiers": ["High"], "data_timestamp": "2026-08-23T00:00:00Z"}]
    rows = _merge_results([], res)
    assert rows == [{
        "system_name": "Sol", "distance_ly": 5.0, "conflicts": [], "faction_states": [],
        "tiers": ["High"], "data_timestamp": "2026-08-23T00:00:00Z",
    }]


def test_merge_results_merges_same_system_from_both_lists():
    bgs = [{"system_name": "Sol", "distance_ly": 5.0, "conflicts": [{"war_type": "war"}],
            "faction_states": [], "data_timestamp": "2026-08-23T00:00:00Z"}]
    res = [{"system_name": "Sol", "distance_ly": 5.0, "tiers": ["High"], "data_timestamp": "2026-08-23T01:00:00Z"}]
    rows = _merge_results(bgs, res)
    assert len(rows) == 1
    row = rows[0]
    assert row["conflicts"] == [{"war_type": "war"}]
    assert row["tiers"] == ["High"]
    # freshest timestamp wins
    assert row["data_timestamp"] == "2026-08-23T01:00:00Z"


def test_merge_results_keeps_bgs_timestamp_when_it_is_newer():
    bgs = [{"system_name": "Sol", "distance_ly": 5.0, "conflicts": [], "faction_states": [],
            "data_timestamp": "2026-08-23T05:00:00Z"}]
    res = [{"system_name": "Sol", "distance_ly": 5.0, "tiers": ["Low"], "data_timestamp": "2026-08-23T01:00:00Z"}]
    rows = _merge_results(bgs, res)
    assert rows[0]["data_timestamp"] == "2026-08-23T05:00:00Z"


def test_merge_results_sorted_by_distance():
    bgs = [
        {"system_name": "Far", "distance_ly": 50.0, "conflicts": [], "faction_states": [], "data_timestamp": "2026-08-23T00:00:00Z"},
        {"system_name": "Near", "distance_ly": 5.0, "conflicts": [], "faction_states": [], "data_timestamp": "2026-08-23T00:00:00Z"},
    ]
    rows = _merge_results(bgs, [])
    assert [r["system_name"] for r in rows] == ["Near", "Far"]


# --- _conflicts_text ---

def test_conflicts_text_empty():
    assert _conflicts_text([]) == ""


def test_conflicts_text_war():
    conflicts = [{"war_type": "war", "faction1": "A", "won_days1": 2, "faction2": "B", "won_days2": 1}]
    assert _conflicts_text(conflicts) == "War: A (2) vs B (1)"


def test_conflicts_text_civil_war_and_joins_multiple():
    conflicts = [
        {"war_type": "civilwar", "faction1": "A", "won_days1": 0, "faction2": "B", "won_days2": 3},
        {"war_type": "war", "faction1": "C", "won_days1": 1, "faction2": "D", "won_days2": 1},
    ]
    assert _conflicts_text(conflicts) == "Civil War: A (0) vs B (3) | War: C (1) vs D (1)"


# --- _faction_states_text ---

def test_faction_states_text_empty():
    assert _faction_states_text([]) == ""


def test_faction_states_text_skips_factions_with_no_active_states():
    factions = [{"name": "A", "active_states": []}]
    assert _faction_states_text(factions) == ""


def test_faction_states_text_formats_single_faction():
    factions = [{"name": "A", "active_states": [{"State": "Boom"}, {"State": "War"}]}]
    assert _faction_states_text(factions) == "A: Boom, War"


def test_faction_states_text_joins_multiple_factions():
    factions = [
        {"name": "A", "active_states": [{"State": "Boom"}]},
        {"name": "B", "active_states": [{"State": "Famine"}]},
    ]
    assert _faction_states_text(factions) == "A: Boom | B: Famine"
