"""Tests for derive_conflicts_from_factions_states() -- pure function, no
network needed. EDSM's factions endpoint has no Conflicts/WonDays data at
all (confirmed live against a real system in civil war, HIP 22052); this
synthesizes a Conflicts-shaped entry from factions sharing a War/CivilWar
FactionState so the Combat System Status tab can still show "at war,
between these factions" from EDSM alone, without EDDN/journal coverage."""
from edc.core.edsm_faction_lookup import derive_conflicts_from_factions_states


def _faction(name, state="None"):
    return {"Name": name, "FactionState": state, "ActiveStates": [], "PendingStates": [], "RecoveringStates": []}


def test_no_combatants_returns_empty():
    factions = [_faction("A"), _faction("B", state="Boom")]
    assert derive_conflicts_from_factions_states(factions) == []


def test_only_one_faction_in_war_state_returns_empty():
    # A war needs two sides -- one faction alone in "War" state (shouldn't
    # happen in real data, but defensive) must not synthesize a conflict.
    factions = [_faction("A", state="War"), _faction("B")]
    assert derive_conflicts_from_factions_states(factions) == []


def test_two_factions_in_war_pairs_them():
    factions = [_faction("A", state="War"), _faction("B", state="War"), _faction("C")]
    result = derive_conflicts_from_factions_states(factions)
    assert len(result) == 1
    assert result[0]["WarType"] == "war"
    assert result[0]["Faction1"]["Name"] == "A"
    assert result[0]["Faction2"]["Name"] == "B"
    assert result[0]["Status"] == ""


def test_civil_war_state_with_space_normalizes_to_civilwar():
    # Confirmed live: EDSM's actual FactionState value is "Civil war"
    # (with a space), not the journal's own "CivilWar" -- must normalize
    # to match what save_system_bgs_status's own WarType filter expects.
    factions = [_faction("A", state="Civil war"), _faction("B", state="Civil war")]
    result = derive_conflicts_from_factions_states(factions)
    assert len(result) == 1
    assert result[0]["WarType"] == "civilwar"


def test_war_and_civilwar_simultaneously_produce_two_conflicts():
    factions = [
        _faction("A", state="War"), _faction("B", state="War"),
        _faction("C", state="Civil war"), _faction("D", state="Civil war"),
    ]
    result = derive_conflicts_from_factions_states(factions)
    assert len(result) == 2
    war_types = {c["WarType"] for c in result}
    assert war_types == {"war", "civilwar"}


def test_won_days_are_not_included():
    # No score data exists from EDSM at all -- must not fabricate one.
    factions = [_faction("A", state="War"), _faction("B", state="War")]
    result = derive_conflicts_from_factions_states(factions)
    assert "WonDays" not in result[0]["Faction1"]
    assert "WonDays" not in result[0]["Faction2"]


def test_non_dict_entries_are_ignored():
    factions = [_faction("A", state="War"), None, "not a dict", _faction("B", state="War")]
    result = derive_conflicts_from_factions_states(factions)
    assert len(result) == 1
