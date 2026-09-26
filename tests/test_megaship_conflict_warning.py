"""Megaship "under attack" warning -- an active War/CivilWar between two
minor factions in the megaship's system is the journal-verified signal
(HIP 19591 on 2026-09-19, HIP 108729 on 2026-09-26: 11 hostiles at the
megaship, all from one combatant, SupercruiseDestinationDrop Threat 0).
HIP 108729's conflict had Status "" (not "active"), so only "pending"
is excluded."""
from types import SimpleNamespace

from edc.core.bgs_conflicts import active_system_war
from edc.ui.main_window import MainWindow

_CIVIL_WAR = {
    "WarType": "civilwar", "Status": "",
    "Faction1": {"Name": "HIP 108729 Empire League", "Stake": "Huber Horticultural", "WonDays": 0},
    "Faction2": {"Name": "HIP 108729 Free", "Stake": "Bailly Station", "WonDays": 2},
}


def test_civil_war_with_blank_status_counts():
    assert active_system_war([_CIVIL_WAR]) == ("Civil war", "HIP 108729 Empire League", "HIP 108729 Free")


def test_active_war_counts():
    war = {"WarType": "war", "Status": "active", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}
    assert active_system_war([war]) == ("War", "A", "B")


def test_pending_war_election_and_empty_do_not_count():
    pending = dict(_CIVIL_WAR, Status="pending")
    election = dict(_CIVIL_WAR, WarType="election")
    assert active_system_war([pending, election]) is None
    assert active_system_war([]) is None
    assert active_system_war(None) is None


def _fake_self(conflicts, pp_power="", ctrl="", pp_state=""):
    return SimpleNamespace(
        cfg=SimpleNamespace(tts_enabled=True, tts_events={"FSSSignalDiscovered": True}),
        _tts_megaship_announced=set(),
        megaship_tracker=SimpleNamespace(has_seen=lambda key: False),
    ), SimpleNamespace(
        system_address=560249932147, system_conflicts=conflicts, pp_power=pp_power,
        system_controlling_power=ctrl, system_powerplay_state=pp_state,
    )


_MEGASHIP_EVT = {"event": "FSSSignalDiscovered", "SystemAddress": 560249932147,
                 "SignalName": "PER-251 Bellmarsh-class Reformatory", "SignalType": "Megaship"}


def test_megaship_callout_warns_about_civil_war_even_when_not_pledged():
    fake_self, state = _fake_self([_CIVIL_WAR])
    phrase = MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state)
    assert "civil war" in phrase.lower()
    assert "hostiles" in phrase.lower()


def test_megaship_callout_combines_merit_phrase_and_warning():
    fake_self, state = _fake_self([_CIVIL_WAR], pp_power="Aisling Duval", ctrl="Aisling Duval", pp_state="Fortified")
    phrase = MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state)
    assert "reinforce" in phrase.lower()
    assert "civil war" in phrase.lower()


def test_megaship_callout_warns_once_per_signal():
    fake_self, state = _fake_self([_CIVIL_WAR])
    MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state)
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state) == ""


def test_megaship_callout_unchanged_without_conflict():
    fake_self, state = _fake_self([], pp_power="Aisling Duval", ctrl="Aisling Duval", pp_state="Fortified")
    phrase = MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state)
    assert "reinforce" in phrase.lower()
    assert "hostiles" not in phrase.lower()
    fake_self, state = _fake_self([])
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", _MEGASHIP_EVT, state) == ""


def test_hud_suffix_names_both_sides_escaped():
    suffix = MainWindow._megaship_conflict_hud_suffix(
        [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A&B"}, "Faction2": {"Name": "<C>"}}]
    )
    assert suffix == " — ⚠ War: A&amp;B vs &lt;C&gt;, expect hostiles"
    assert MainWindow._megaship_conflict_hud_suffix([]) == ""


# --- signals written before the FSDJump belong to the NEXT system ---
# Confirmed live 2026-09-26: Baudurotri's megaship signal arrived before its
# FSDJump, so the callout used the previous system's (Tucanae, Unoccupied)
# PowerPlay state and wrongly said "Scan for acquisition merits".

def test_signal_for_a_system_we_are_not_in_yet_is_not_announced():
    fake_self, state = _fake_self([_CIVIL_WAR], pp_power="Aisling Duval", ctrl="", pp_state="Unoccupied")
    evt = dict(_MEGASHIP_EVT, SystemAddress=4207155221234)
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", evt, state) == ""
    # not marked as announced -- the post-jump re-fire must still be able to announce it
    state.system_address = 4207155221234
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", evt, state) != ""


def test_compromised_nav_beacon_for_another_system_is_not_announced():
    fake_self, state = _fake_self([], pp_power="Aisling Duval", ctrl="Aisling Duval", pp_state="Fortified")
    fake_self._tts_cnb_announced = set()
    same_system = {"event": "FSSSignalDiscovered", "SystemAddress": 560249932147, "SignalType": "NavBeacon",
                   "SignalName": "$MULTIPLAYER_SCENARIO80_TITLE;", "SignalName_Localised": "Compromised Nav Beacon"}
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", same_system, state) != ""  # control case
    fake_self._tts_cnb_announced = set()
    evt = {"event": "FSSSignalDiscovered", "SystemAddress": 4207155221234, "SignalType": "NavBeacon",
           "SignalName": "$MULTIPLAYER_SCENARIO80_TITLE;", "SignalName_Localised": "Compromised Nav Beacon"}
    assert MainWindow._tts_router(fake_self, "FSSSignalDiscovered", evt, state) == ""
    assert fake_self._tts_cnb_announced == set()
