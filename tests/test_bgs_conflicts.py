"""Tests for parse_powerplay_conflict_progress() -- pure function, no Qt
needed. Extracted from three near-identical copies (event_engine.py's
Location and FSDJump branches, plus exploration.py's own FSDJump
handling of the same event) that had drifted to inconsistent overwrite
semantics -- one always assigned the result, the other only assigned when
truthy, leaving stale conflict-progress data on screen after leaving a
contested system."""
from edc.core.bgs_conflicts import parse_powerplay_conflict_progress


def test_parses_valid_records():
    event = {"PowerplayConflictProgress": [
        {"Power": "Yuri Grom", "ConflictProgress": 0.42},
        {"Power": "Zemina Torval", "ConflictProgress": 0.1},
    ]}
    assert parse_powerplay_conflict_progress(event) == {"Yuri Grom": 0.42, "Zemina Torval": 0.1}


def test_missing_field_returns_empty_dict():
    assert parse_powerplay_conflict_progress({}) == {}


def test_empty_list_returns_empty_dict():
    assert parse_powerplay_conflict_progress({"PowerplayConflictProgress": []}) == {}


def test_skips_records_with_non_string_power():
    event = {"PowerplayConflictProgress": [{"Power": 123, "ConflictProgress": 0.5}]}
    assert parse_powerplay_conflict_progress(event) == {}


def test_skips_records_with_non_numeric_progress():
    event = {"PowerplayConflictProgress": [{"Power": "Yuri Grom", "ConflictProgress": "not a number"}]}
    assert parse_powerplay_conflict_progress(event) == {}


def test_skips_non_dict_records():
    event = {"PowerplayConflictProgress": [None, "garbage", {"Power": "Yuri Grom", "ConflictProgress": 0.7}]}
    assert parse_powerplay_conflict_progress(event) == {"Yuri Grom": 0.7}


def test_int_progress_is_converted_to_float():
    event = {"PowerplayConflictProgress": [{"Power": "Yuri Grom", "ConflictProgress": 1}]}
    result = parse_powerplay_conflict_progress(event)
    assert result == {"Yuri Grom": 1.0}
    assert isinstance(result["Yuri Grom"], float)
