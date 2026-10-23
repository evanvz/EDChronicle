"""Callout phrase review 2026-10-23: one body reads as one, not "1 bodies"; the
startup line varies; fixed wording bugs stay fixed."""
from edc.audio.handlers.combat import CombatPhrases
from edc.audio.handlers.exploration import ExplorationPhrases
from edc.audio.handlers.status import StatusPhrases


def test_single_body_wording():
    for _ in range(30):
        assert "1 bodies" not in ExplorationPhrases.valuable_bodies_summary(1)
        assert "1 bodies" not in ExplorationPhrases.fss_complete(1)
    assert "15" in ExplorationPhrases.fss_complete(15)


def test_startup_line_varies_and_old_wording_bugs_are_gone():
    assert len(set(StatusPhrases.SYSTEMS_ONLINE)) >= 5
    assert not any("awarded received" in p for p in CombatPhrases.KILL_BOND)
    assert not any("Shields down" in p for p in CombatPhrases.UNDER_ATTACK)
