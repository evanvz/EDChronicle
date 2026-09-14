"""MainWindow._handle_combat_quip()'s ShipTargeted branch -- reason ==
"enemy" from _callout_reason() also covers plain LegalStatus Hostile/
Enemy and a Wanted-rank match, neither of which implies any PowerPlay
stake in the current system. The PowerPlay "enemy of the cause" wording
must only fire when our own pledged power actually has stake here
(controls it, is a contesting power, or it's Contested) -- confirmed
live: a Li Yong-Rui CZ ship got that phrasing in a system the player's
pledged power had zero presence in, purely because its power differed
from ours. Uses the fake-self/SimpleNamespace pattern already
established for MainWindow method tests (see
test_bounty_if_candidates_cache.py)."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(pledged, ctrl, system_powers, pp_state="", ranks=None, ship_has_weapons=None):
    return SimpleNamespace(
        cfg=SimpleNamespace(tts_enabled=True),
        state=SimpleNamespace(
            pp_power=pledged,
            system_controlling_power=ctrl,
            system_powers=system_powers,
            system_powerplay_state=pp_state,
            factions=[],
            ranks=ranks or {},
            ship_has_weapons=ship_has_weapons,
        ),
        _commander_quip_cooldown_until=0.0,
        tts=SimpleNamespace(speak=lambda *a, **k: None),
    )


def _ship_targeted_event(power, legal_status):
    return {
        "event": "ShipTargeted", "TargetLocked": True, "ScanStage": 3,
        "Power": power, "LegalStatus": legal_status, "Bounty": 0,
        "Faction": "Some Faction", "PilotRank": "Competent",
    }


def test_hostile_ship_of_uninvolved_power_does_not_get_pp_wording():
    # Our pledged power has ZERO stake in this system (not controlling,
    # not a contesting power, not Contested) -- the ship is LegalStatus
    # Hostile (unrelated to PowerPlay) and belongs to the system's
    # rival-power controller. Must not get "enemy of the cause" wording.
    fake_self = _fake_self(pledged="Aisling Duval", ctrl="Li Yong-Rui", system_powers=["Li Yong-Rui"], pp_state="Exploited")
    quips = []
    fake_self.tts.speak = lambda q, **k: quips.append(q)
    MainWindow._handle_combat_quip(
        fake_self, "ShipTargeted", _ship_targeted_event("Li Yong-Rui", "Hostile"),
    )
    assert quips, "expected a quip to fire (LegalStatus Hostile is always callout-worthy)"
    assert "enemy of the cause" not in quips[0].lower()
    assert "no bounty risk here" not in quips[0].lower()
    assert "rival power" not in quips[0].lower()


def test_pp_rival_ship_when_we_control_system_gets_pp_wording():
    fake_self = _fake_self(pledged="Aisling Duval", ctrl="Aisling Duval", system_powers=["Aisling Duval"], pp_state="Fortified")
    quips = []
    fake_self.tts.speak = lambda q, **k: quips.append(q)
    MainWindow._handle_combat_quip(
        fake_self, "ShipTargeted", _ship_targeted_event("Li Yong-Rui", "Clean"),
    )
    assert quips
    from edc.audio.handlers.combat import CombatPhrases
    assert quips[0] in CombatPhrases.POWERPLAY_ENEMY_SCAN


def test_pp_rival_ship_in_contested_system_gets_pp_wording():
    fake_self = _fake_self(pledged="Aisling Duval", ctrl="Li Yong-Rui", system_powers=["Li Yong-Rui", "Aisling Duval"], pp_state="Contested")
    quips = []
    fake_self.tts.speak = lambda q, **k: quips.append(q)
    MainWindow._handle_combat_quip(
        fake_self, "ShipTargeted", _ship_targeted_event("Li Yong-Rui", "Clean"),
    )
    assert quips
    from edc.audio.handlers.combat import CombatPhrases
    assert quips[0] in CombatPhrases.POWERPLAY_ENEMY_SCAN
