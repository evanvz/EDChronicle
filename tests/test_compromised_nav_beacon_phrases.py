"""ExplorationPhrases.compromised_nav_beacon_pp_merits() picks the right
phrase pool per PowerPlay category -- pure function, no Qt needed."""
from edc.audio.handlers.exploration import ExplorationPhrases


def test_reinforcement_picks_from_reinforcement_pool():
    result = ExplorationPhrases.compromised_nav_beacon_pp_merits("reinforcement")
    assert result in ExplorationPhrases.CNB_PP_REINFORCEMENT


def test_undermining_picks_from_undermining_pool():
    result = ExplorationPhrases.compromised_nav_beacon_pp_merits("undermining")
    assert result in ExplorationPhrases.CNB_PP_UNDERMINING


def test_acquisition_picks_from_acquisition_pool():
    result = ExplorationPhrases.compromised_nav_beacon_pp_merits("acquisition")
    assert result in ExplorationPhrases.CNB_PP_ACQUISITION


def test_unknown_activity_defaults_to_reinforcement_pool():
    result = ExplorationPhrases.compromised_nav_beacon_pp_merits("")
    assert result in ExplorationPhrases.CNB_PP_REINFORCEMENT
