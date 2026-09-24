"""faction_expansion_dialog._is_expanding() -- detects Frontier's own
"Expansion" BGS state from a faction_snapshots row, either as the
primary faction_state or listed in active_states (JSON string column).
This is what triggers the tracker's "keep supporting the push, influence
decays daily for about a week" banner."""
from edc.ui.panels.faction_expansion_dialog import _is_expanding


def test_expansion_as_primary_state():
    assert _is_expanding({"faction_state": "Expansion", "active_states": None}) is True


def test_expansion_case_insensitive():
    assert _is_expanding({"faction_state": "EXPANSION", "active_states": None}) is True


def test_expansion_in_active_states_json():
    row = {"faction_state": "None", "active_states": '[{"State": "Expansion", "Trend": 0}]'}
    assert _is_expanding(row) is True


def test_boom_is_not_expansion():
    assert _is_expanding({"faction_state": "Boom", "active_states": None}) is False


def test_none_snapshot_is_not_expansion():
    assert _is_expanding(None) is False


def test_empty_snapshot_is_not_expansion():
    assert _is_expanding({}) is False


def test_malformed_active_states_json_does_not_raise():
    row = {"faction_state": None, "active_states": "not valid json"}
    assert _is_expanding(row) is False


def test_other_active_state_does_not_falsely_match():
    row = {"faction_state": None, "active_states": '[{"State": "CivilUnrest"}]'}
    assert _is_expanding(row) is False
