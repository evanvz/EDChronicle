"""bgs_conflicts.has_raid_opportunity_state() -- Civil Unrest/Infrastructure
Failure indicate a faction's settlements run with reduced or no security
(community-confirmed: Civil Unrest often still burning, Infrastructure
Failure just dark, both lootable) -- the signal behind finding an
abandoned/lightly-defended settlement to raid. Worth tracking even as a
faction's only active state, unlike is_multistate_faction()'s 2+ rule."""
from edc.core.bgs_conflicts import has_raid_opportunity_state


def test_civil_unrest_alone_is_a_raid_opportunity():
    assert has_raid_opportunity_state({"ActiveStates": [{"State": "CivilUnrest"}]}) is True


def test_infrastructure_failure_alone_is_a_raid_opportunity():
    assert has_raid_opportunity_state({"ActiveStates": [{"State": "InfrastructureFailure"}]}) is True


def test_case_insensitive_matching():
    assert has_raid_opportunity_state({"ActiveStates": [{"State": "civilunrest"}]}) is True


def test_checks_pending_and_recovering_buckets_too():
    assert has_raid_opportunity_state({"PendingStates": [{"State": "CivilUnrest"}]}) is True
    assert has_raid_opportunity_state({"RecoveringStates": [{"State": "InfrastructureFailure"}]}) is True


def test_ordinary_single_state_is_not_a_raid_opportunity():
    assert has_raid_opportunity_state({"ActiveStates": [{"State": "Boom"}]}) is False


def test_no_states_is_not_a_raid_opportunity():
    assert has_raid_opportunity_state({}) is False
