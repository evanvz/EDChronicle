"""Achenar 2026-10-23: flying an unarmed Caspian Explorer, a scanned Li Yong-Rui
ship put "PP enemy scan ... | You have no weapons fitted - do not engage" on the
Overview. The voice callout is already silent when unarmed; the Overview alert
now is too, while an armed ship still gets it."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState

SCAN = {"event": "ShipTargeted", "timestamp": "2026-10-23T16:20:00Z", "TargetLocked": True, "ScanStage": 3,
        "Ship": "ferdelance", "Ship_Localised": "Fer-de-Lance", "PilotName_Localised": "Hendrik Zielke",
        "PilotRank": "Master", "Power": "Li Yong-Rui", "LegalStatus": "Clean", "Faction": "Some Faction"}


def _engine(tmp_path, armed):
    state = GameState()
    state.pp_power, state.system_controlling_power = "Aisling Duval", "A. Lavigny-Duval"
    state.system_powers, state.ship_has_weapons = ["Aisling Duval", "A. Lavigny-Duval"], armed
    return EventEngine(state, tmp_path)


def test_unarmed_ship_gets_no_enemy_scan_alert(tmp_path):
    eng = _engine(tmp_path, armed=False)
    state, msgs = eng.process(dict(SCAN))
    assert not state.pp_enemy_alerts and not msgs


def test_armed_ship_still_gets_it(tmp_path):
    eng = _engine(tmp_path, armed=True)
    state, _ = eng.process(dict(SCAN))
    assert state.pp_enemy_alerts and "PP enemy scan" in state.pp_enemy_alerts[0]
