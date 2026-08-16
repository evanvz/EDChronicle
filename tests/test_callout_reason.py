"""Tests for the combat voice-callout gate -- pure function, no Qt needed.
Matches tests/test_engage_risk.py's structure/imports."""
import pytest

from edc.core.event_engine import EventEngine, _callout_reason
from edc.core.state import GameState
from edc.audio.handlers.combat import CombatPhrases


# --- _callout_reason ---

def test_hostile_is_enemy_unconditional():
    result = _callout_reason(
        hostile=True, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_legal_enemy_is_enemy_unconditional():
    result = _callout_reason(
        hostile=False, enemy=True, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_pp_rival_in_our_space_is_enemy():
    result = _callout_reason(
        hostile=False, enemy=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_pp_rival_outside_our_space_is_not_enemy():
    # Regression shape matching _engage_risk's own Vargerson case: rival
    # power ship, but we do NOT control/contest this system.
    result = _callout_reason(
        hostile=False, enemy=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result is None


def test_top_rank_in_pp_relevant_system_is_high_value():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result == "high_value"


def test_top_rank_with_squadron_at_war_is_high_value():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="Some Other Faction", pledged="",
        squadron_faction="Our Faction", ctrl="", system_powers=[], pp_state="",
        rank="Dangerous", squadron_at_war=True,
    )
    assert result == "high_value"


def test_top_rank_in_irrelevant_system_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result is None


def test_low_rank_in_relevant_system_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Competent", squadron_at_war=False,
    )
    assert result is None


def test_plain_clean_no_signals_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Harmless", squadron_at_war=False,
    )
    assert result is None


def test_own_power_never_called_out_even_if_hostile():
    # A ship can't really be both "ours" and Hostile in practice, but the
    # own-side exclusion must still win if it somehow were -- checked first,
    # unconditionally, per the design.
    result = _callout_reason(
        hostile=True, enemy=False, power="Aisling Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result is None


def test_own_squadron_faction_never_called_out():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="Our Faction", pledged="",
        squadron_faction="Our Faction", ctrl="", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=True,
    )
    assert result is None


def test_contested_pp_state_counts_as_relevant():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=[], pp_state="Contested",
        rank="Deadly", squadron_at_war=False,
    )
    assert result == "high_value"


def test_system_powers_membership_counts_as_relevant():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=["Aisling Duval"], pp_state="",
        rank="Deadly", squadron_at_war=False,
    )
    assert result == "high_value"


# --- combat_contacts write path -- confirms "Enemy" lands on combat_contacts ---

@pytest.fixture
def engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _ship_targeted_event(legal_status, pilot="Test Pilot", ship="Vulture"):
    return {
        "event": "ShipTargeted", "TargetLocked": True, "ScanStage": 3,
        "PilotName": pilot, "Ship": ship, "LegalStatus": legal_status,
    }


def test_enemy_legal_status_sets_enemy_field(engine):
    engine.process(_ship_targeted_event("Enemy"))
    contact = next(iter(engine.state.combat_contacts.values()))
    assert contact["Enemy"] is True


def test_clean_legal_status_leaves_enemy_field_false(engine):
    engine.process(_ship_targeted_event("Clean"))
    contact = next(iter(engine.state.combat_contacts.values()))
    assert contact["Enemy"] is False


# --- CombatPhrases.high_value_contact_scan() ---

def test_high_value_contact_scan_returns_nonempty_string():
    text = CombatPhrases.high_value_contact_scan()
    assert isinstance(text, str) and text
    assert text in CombatPhrases.HIGH_VALUE_CONTACT_SCAN
