"""Tests for the combat voice-callout gate -- pure function, no Qt needed.
Matches tests/test_engage_risk.py's structure/imports."""
import pytest

from edc.core.event_engine import EventEngine, _callout_reason
from edc.core.state import GameState
from edc.audio.handlers.combat import CombatPhrases


# --- _callout_reason ---

def test_hostile_is_enemy_unconditional():
    result = _callout_reason(
        hostile=True, enemy=False, wanted=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
    )
    assert result == "enemy"


def test_legal_enemy_is_enemy_unconditional():
    result = _callout_reason(
        hostile=False, enemy=True, wanted=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
    )
    assert result == "enemy"


def test_wanted_is_enemy_unconditional():
    # Confirmed via live testing: a plain Wanted ship must always be called
    # out, regardless of rank/PP/BGS relevance -- the game has already
    # decided this is fair game.
    result = _callout_reason(
        hostile=False, enemy=False, wanted=True, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
    )
    assert result == "enemy"


def test_pp_rival_in_our_space_is_enemy():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
    )
    assert result == "enemy"


def test_pp_rival_outside_our_space_is_not_enemy():
    # Regression shape matching _engage_risk's own Vargerson case: rival
    # power ship, but we do NOT control/contest this system.
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
    )
    assert result is None


def test_top_rank_alone_is_none():
    # A rank-alone trigger existed once (top-3-tier ship in a PP/BGS-
    # relevant system) -- removed after live testing showed it firing for
    # plenty of Clean, non-wanted ships the player had no reason to act
    # on. Rank alone -- even in a PP-relevant system -- is no longer
    # callout-worthy; only Hostile/Enemy/Wanted/PP-rival are.
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
    )
    assert result is None


def test_plain_clean_no_signals_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
    )
    assert result is None


def test_own_power_never_called_out_even_if_wanted():
    # A ship can't really be both "ours" and Wanted in practice, but the
    # own-side exclusion must still win if it somehow were -- checked
    # first, unconditionally, per the design: we don't shoot our own.
    result = _callout_reason(
        hostile=False, enemy=False, wanted=True, power="Aisling Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
    )
    assert result is None


def test_own_squadron_faction_never_called_out():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=True, power="", faction="Our Faction", pledged="",
        squadron_faction="Our Faction", ctrl="", system_powers=[], pp_state="",
    )
    assert result is None


def test_internal_security_faction_never_called_out():
    # Excluded regardless of category -- even Hostile/Enemy -- same as the
    # own-side exclusion. Case-insensitive match on the faction string.
    result = _callout_reason(
        hostile=True, enemy=True, wanted=True, power="A. Lavigny-Duval", faction="Some INTERNAL Security Force",
        pledged="Aisling Duval", squadron_faction="", ctrl="Aisling Duval", system_powers=[],
        pp_state="",
    )
    assert result is None


def test_security_service_faction_never_called_out():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=True, power="", faction="Federal Security Service",
        pledged="", squadron_faction="", ctrl="", system_powers=[], pp_state="",
    )
    assert result is None


def test_contested_pp_state_counts_as_relevant_for_pp_rival():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=[], pp_state="Contested",
    )
    assert result == "enemy"


def test_system_powers_membership_counts_as_relevant_for_pp_rival():
    result = _callout_reason(
        hostile=False, enemy=False, wanted=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=["Aisling Duval"], pp_state="",
    )
    assert result == "enemy"


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
