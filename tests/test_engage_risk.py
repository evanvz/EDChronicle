"""Tests for the combat engage-risk verdict -- pure functions, no Qt
needed."""
from edc.core.event_engine import _engage_risk
from edc.audio.handlers.combat import CombatPhrases


# --- _engage_risk ---

def test_wanted_is_safe():
    assert _engage_risk(True, False, "", "", "", "") == "safe"


def test_hostile_is_safe():
    assert _engage_risk(False, True, "", "", "", "") == "safe"


def test_pp_enemy_in_my_own_territory_is_safe():
    # Rival power ship encountered while I control this system myself.
    result = _engage_risk(
        wanted=False, hostile=False, power="A. Lavigny-Duval",
        pledged="Aisling Duval", ctrl="Aisling Duval", government="Patronage",
    )
    assert result == "safe"


def test_pp_enemy_outside_my_own_territory_is_not_safe():
    # Regression test for the exact Vargerson case: rival power ship, but
    # I do NOT control this system (someone else does) -- must NOT be
    # misclassified as safe just because the powers differ.
    result = _engage_risk(
        wanted=False, hostile=False, power="Aisling Duval",
        pledged="Aisling Duval", ctrl="A. Lavigny-Duval", government="Confederacy",
    )
    assert result == "unknown"


def test_anarchy_government_is_caution():
    result = _engage_risk(
        wanted=False, hostile=False, power="", pledged="", ctrl="", government="Anarchy",
    )
    assert result == "caution"


def test_plain_clean_no_signals_is_unknown():
    assert _engage_risk(False, False, "", "", "", "") == "unknown"


def test_safe_conditions_checked_before_anarchy():
    # A Wanted target in an Anarchy system is still unconditionally safe
    # (lawful bounty hunting), not merely "caution".
    result = _engage_risk(
        wanted=True, hostile=False, power="", pledged="", ctrl="", government="Anarchy",
    )
    assert result == "safe"


# --- CombatPhrases.ship_targeted() engage_risk clause ---

def test_ship_targeted_appends_safe_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="safe",
    )
    assert text.endswith("Clear to engage.")


def test_ship_targeted_appends_caution_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="caution",
    )
    assert text.endswith("Caution -- anarchy space, not guaranteed near a port.")


def test_ship_targeted_appends_unknown_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="unknown",
    )
    assert text.endswith("Engaging will likely draw a bounty.")


def test_ship_targeted_appends_no_clause_when_risk_not_given():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False,
    )
    assert text == "Vulture Competent."
