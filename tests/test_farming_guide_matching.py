"""Tests for the Intel tab's live farming-guide matching -- pure
functions, no Qt/QApplication needed (matches
tests/test_active_war_opponent.py's pattern of importing panel-module
free functions directly)."""
from types import SimpleNamespace

import pytest

from edc.core.farming_locations import FarmingLocations
from edc.ui.panels.intel_panel import (
    _get_system_opportunities,
    _entry_matches_system,
    _state_text_to_tags,
    _with_matched_examples,
)


def _state(government="", allegiance="", security="", economy="", factions=None):
    return SimpleNamespace(
        system_government=government,
        system_allegiance=allegiance,
        system_security=security,
        system_economy=economy,
        factions=factions or [],
    )


# --- _get_system_opportunities: new tags ---

def test_civil_unrest_tag_from_active_states():
    state = _state(factions=[
        {"FactionState": "None", "ActiveStates": [{"State": "CivilUnrest", "Trend": 0}]}
    ])
    assert "civil_unrest" in _get_system_opportunities(state)


def test_infrastructure_failure_tag_from_active_states():
    state = _state(factions=[
        {"FactionState": "None", "ActiveStates": [{"State": "InfrastructureFailure", "Trend": 0}]}
    ])
    assert "infrastructure_failure" in _get_system_opportunities(state)


def test_empire_tag_from_allegiance():
    state = _state(allegiance="Empire")
    assert "empire" in _get_system_opportunities(state)


def test_federation_tag_from_allegiance():
    state = _state(allegiance="Federation")
    assert "federation" in _get_system_opportunities(state)


def test_empty_state_produces_no_tags():
    assert _get_system_opportunities(_state()) == set()


# --- _state_text_to_tags ---

@pytest.mark.parametrize("text,expected", [
    ("Outbreak", {"outbreak"}),
    ("Imperial allegiance / any state", {"empire"}),
    ("Federal allegiance / any state", {"federation"}),
    ("War / Civil War", {"war"}),
    ("Boom", {"boom"}),
    ("Something Unrecognized", set()),
])
def test_state_text_to_tags(text, expected):
    assert _state_text_to_tags(text) == expected


# --- _entry_matches_system ---

def test_state_tags_entry_matches_overlapping_live_tag():
    loc = {"name": "HGE Pharmaceutical Isolators", "state_tags": ["outbreak"]}
    assert _entry_matches_system(loc, {"outbreak"}) == {"outbreak"}


def test_hge_pharmaceutical_isolators_no_longer_matches_boom():
    # Regression test for the original bug: this entry's text contains
    # "hge"/"high grade", which the OLD keyword search wrongly matched
    # against the boom tag. It must only match outbreak now.
    loc = {"name": "HGE Pharmaceutical Isolators", "state_tags": ["outbreak"]}
    assert _entry_matches_system(loc, {"boom"}) == set()


def test_high_wake_scans_never_matches_anything():
    # Regression test for the original bug: this entry has no
    # state_tags at all (its "wake scan" text accidentally matched the
    # OLD anarchy keyword search). No state_tags + no examples means it
    # never live-matches, regardless of live tags.
    loc = {"name": "High Wake Scans", "method": "Scan high wakes in busy systems"}
    assert _entry_matches_system(loc, {"anarchy", "boom", "war"}) == set()


def test_hge_manufactured_entry_matches_only_the_relevant_example():
    loc = {
        "name": "High Grade Emissions (HGE)",
        "examples": [
            {"material": "Pharmaceutical Isolators", "state": "Outbreak"},
            {"material": "Imperial Shielding", "state": "Imperial allegiance / any state"},
            {"material": "Core Dynamics Composites", "state": "Federal allegiance / any state"},
            {"material": "Military Grade Alloys", "state": "War / Civil War"},
            {"material": "Proto Heat Radiators", "state": "Boom"},
        ],
    }
    assert _entry_matches_system(loc, {"boom"}) == {"boom"}


# --- _with_matched_examples: shared by every card rendering farm entries ---

_HGE_ENTRY = {
    "name": "High Grade Emissions (HGE)",
    "examples": [
        {"material": "Pharmaceutical Isolators", "state": "Outbreak"},
        {"material": "Proto Heat Radiators", "state": "Boom"},
    ],
}


def test_with_matched_examples_narrows_to_the_matching_example_only():
    matched_tags = _entry_matches_system(_HGE_ENTRY, {"boom"})
    entry = _with_matched_examples(_HGE_ENTRY, matched_tags, {"boom"})
    assert entry is not _HGE_ENTRY
    assert [ex["material"] for ex in entry["_matched_examples"]] == ["Proto Heat Radiators"]
    # Original record is untouched (shallow copy, not mutated in place).
    assert "_matched_examples" not in _HGE_ENTRY


def test_with_matched_examples_returns_entry_unchanged_when_no_match():
    entry = _with_matched_examples(_HGE_ENTRY, set(), {"outbreak"})
    assert entry is _HGE_ENTRY


def test_with_matched_examples_returns_entry_unchanged_when_no_examples_field():
    loc = {"name": "Anarchy-government systems", "state_tags": ["anarchy"]}
    matched_tags = _entry_matches_system(loc, {"anarchy"})
    entry = _with_matched_examples(loc, matched_tags, {"anarchy"})
    assert entry is loc


# --- FarmingLocations loader: state_tags round-trip ---

def test_loader_carries_state_tags_through(tmp_path):
    data = {
        "farming_locations": {
            "encoded": [
                {
                    "name": "HGE Pharmaceutical Isolators",
                    "method": "Search Outbreak systems for HGEs",
                    "key_materials": ["Pharmaceutical Isolators"],
                    "state_tags": ["outbreak"],
                }
            ]
        }
    }
    import json
    (tmp_path / "elite_farming_locations.json").write_text(json.dumps(data), encoding="utf-8")

    fl = FarmingLocations(tmp_path)
    records = fl._records
    assert len(records) == 1
    assert records[0]["state_tags"] == ["outbreak"]
