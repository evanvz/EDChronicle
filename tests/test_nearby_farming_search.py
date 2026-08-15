"""Tests for the nearest-farming-opportunity search: the repository's
raw data fetch, the pure tag-derivation function, and the pure
merge/filter/sort function. No Qt/QApplication needed for the pure
functions (matches tests/test_farming_guide_matching.py's pattern)."""
import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.ui.panels.intel_panel import (
    _tags_from_faction_snapshot_row,
    _build_nearby_farming_results,
)


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_system(repo, system_address, system_name, x, y, z):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_snapshot(
    repo, system_address, faction_name="Test Faction", government="Democracy",
    allegiance="Independent", faction_state="None", active_states=None,
    is_controlling=True, snapshot_date="2026-08-15",
):
    faction = {
        "Name": faction_name,
        "Government": government,
        "Allegiance": allegiance,
        "FactionState": faction_state,
    }
    if active_states is not None:
        faction["ActiveStates"] = active_states
    repo.save_faction_snapshot(
        system_address, faction, snapshot_date, is_controlling, snapshot_date, "edsm"
    )


# --- Repository.get_controlling_faction_snapshots_with_coords ---

def test_returns_controlling_faction_with_coords(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert len(rows) == 1
    assert rows[0]["system_name"] == "Sol"
    assert rows[0]["faction_state"] == "Boom"
    assert rows[0]["x"] == 0.0


def test_excludes_non_controlling_faction(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_name="Minor Faction", faction_state="Boom", is_controlling=False)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert rows == []


def test_only_most_recent_snapshot_date_returned(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_state="War", is_controlling=True, snapshot_date="2026-08-10")
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True, snapshot_date="2026-08-15")

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert len(rows) == 1
    assert rows[0]["faction_state"] == "Boom"


def test_excludes_system_with_no_coords(repo):
    # No _seed_system coords call -- system_address 1 has a snapshot but
    # no system_coords row, so distance can't be computed.
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (1, "Sol"),
    )
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert rows == []


# --- _tags_from_faction_snapshot_row ---

def test_tags_from_row_anarchy():
    row = {"government": "Anarchy", "allegiance": "Independent", "faction_state": "None", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"anarchy"}


def test_tags_from_row_empire_allegiance():
    row = {"government": "Patronage", "allegiance": "Empire", "faction_state": "None", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"empire"}


def test_tags_from_row_boom_faction_state():
    row = {"government": "Democracy", "allegiance": "Independent", "faction_state": "Boom", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"boom"}


def test_tags_from_row_civil_unrest_active_state():
    row = {
        "government": "Democracy", "allegiance": "Independent", "faction_state": "None",
        "active_states": '[{"State": "CivilUnrest", "Trend": 0}]',
    }
    assert _tags_from_faction_snapshot_row(row) == {"civil_unrest"}


def test_tags_from_row_empty_produces_no_tags():
    row = {"government": "", "allegiance": "", "faction_state": "", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == set()


# --- _build_nearby_farming_results ---

_STATIC_SITE = {
    "name": "Arai's Mine",
    "system": "Iah Bulu",
    "domain": "odyssey_onfoot",
    "key_materials": ["Broad Odyssey material coverage"],
}

_HGE_ENTRY = {
    "name": "High Grade Emissions (HGE)",
    "domain": "manufactured",
    "examples": [
        {"material": "Pharmaceutical Isolators", "state": "Outbreak"},
        {"material": "Proto Heat Radiators", "state": "Boom"},
    ],
}


def test_static_site_produces_result_with_correct_distance():
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[],
        guide_records=[],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Broad Odyssey material coverage"
    assert results[0]["system_name"] == "Iah Bulu"
    assert results[0]["distance_ly"] == 50.0
    assert results[0]["source"] == "static"
    assert results[0]["state"] is None


def test_live_match_produces_result_with_state():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "Boom", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Proto Heat Radiators"
    assert results[0]["system_name"] == "Sol"
    assert results[0]["distance_ly"] == 10.0
    assert results[0]["source"] == "live"
    assert results[0]["state"] == "Boom"


def test_material_filter_narrows_both_sources():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "Boom", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],
        material_filter="proto heat",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Proto Heat Radiators"


def test_results_sorted_nearest_first_across_both_sources():
    near_live_row = {
        "system_name": "Near", "government": "Anarchy", "allegiance": "Independent",
        "faction_state": "None", "active_states": None, "x": 5.0, "y": 0.0, "z": 0.0,
    }
    anarchy_entry = {"name": "Anarchy-government systems", "domain": "odyssey_onfoot",
                      "state_tags": ["anarchy"], "key_materials": ["Broad Odyssey material coverage"]}
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],  # Iah Bulu at distance 50.0
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[near_live_row],  # distance 5.0
        guide_records=[anarchy_entry],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 2
    assert results[0]["system_name"] == "Near"
    assert results[1]["system_name"] == "Iah Bulu"


def test_display_cap_respected():
    live_rows = [
        {
            "system_name": f"System {i}", "government": "Anarchy", "allegiance": "Independent",
            "faction_state": "None", "active_states": None, "x": float(i), "y": 0.0, "z": 0.0,
        }
        for i in range(60)
    ]
    anarchy_entry = {"name": "Anarchy-government systems", "domain": "odyssey_onfoot",
                      "state_tags": ["anarchy"], "key_materials": ["Broad Odyssey material coverage"]}
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=live_rows,
        guide_records=[anarchy_entry],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
        limit=50,
    )
    assert len(results) == 50


def test_unmatched_guide_record_produces_nothing():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "None", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],  # needs outbreak/boom/war/empire/federation, none present
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert results == []
