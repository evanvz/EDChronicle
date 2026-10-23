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


def test_combat_zones_tag_comes_from_the_systems_own_conflicts():
    """ICZ test systems, 2026-10-23: EUW's FactionState was "War" there (its
    Arimavante war) but the system had no Conflicts, so no CZs."""
    from types import SimpleNamespace
    from edc.ui.main_window import MainWindow
    fake = SimpleNamespace(farming_locations=SimpleNamespace(get_for_system=lambda s: []), guardian_ruins=None)
    euw_war = [{"Name": "Elite United Worlds", "FactionState": "War", "ActiveStates": []}]
    quiet = SimpleNamespace(system="ICZ XZ-P b5-1", system_government="", factions=euw_war, system_conflicts=[])
    assert "Combat Zones" not in MainWindow._farming_arrival_brief(fake, quiet)
    war = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}]
    hot = SimpleNamespace(system="Arimavante", system_government="", factions=euw_war, system_conflicts=war)
    assert "Combat Zones active" in MainWindow._farming_arrival_brief(fake, hot)
