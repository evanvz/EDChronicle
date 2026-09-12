"""CombatBgsStatusPanel's status-filter dropdown -- extends the existing
radius search to let the user view/filter systems by BGS status (War/
Civil War, Civil Unrest, Infrastructure Failure) instead of reading every
result manually. _STATUS_FILTERS' matchers are pure and reusable outside
the widget, so tested directly against _merge_results()-shaped rows."""
from edc.ui.panels.combat_bgs_status_panel import _STATUS_FILTERS, _has_state


def _row(conflicts=None, faction_states=None):
    return {"system_name": "Sol", "distance_ly": 1.0, "conflicts": conflicts or [],
            "faction_states": faction_states or [], "tiers": [], "data_timestamp": ""}


def _matcher(label):
    for l, m in _STATUS_FILTERS:
        if l == label:
            return m
    raise KeyError(label)


def test_all_filter_matches_everything():
    assert _matcher("All")(_row()) is True
    assert _matcher("All")(_row(conflicts=[{"war_type": "war"}])) is True


def test_war_civil_war_filter_requires_conflicts():
    assert _matcher("War / Civil War")(_row(conflicts=[{"war_type": "war"}])) is True
    assert _matcher("War / Civil War")(_row()) is False


def test_civil_unrest_filter_matches_active_state():
    row = _row(faction_states=[{"name": "A", "active_states": [{"State": "CivilUnrest"}]}])
    assert _matcher("Civil Unrest")(row) is True
    assert _matcher("Infrastructure Failure")(row) is False


def test_infrastructure_failure_filter_matches_active_state():
    row = _row(faction_states=[{"name": "A", "active_states": [{"State": "InfrastructureFailure"}]}])
    assert _matcher("Infrastructure Failure")(row) is True
    assert _matcher("Civil Unrest")(row) is False


def test_has_state_is_case_insensitive():
    row = _row(faction_states=[{"name": "A", "active_states": [{"State": "civilunrest"}]}])
    assert _has_state(row, "civilunrest") is True


def test_no_matching_state_fails_both_filters():
    row = _row(faction_states=[{"name": "A", "active_states": [{"State": "Boom"}]}])
    assert _matcher("Civil Unrest")(row) is False
    assert _matcher("Infrastructure Failure")(row) is False
