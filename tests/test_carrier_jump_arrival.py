"""Riding a fleet carrier writes CarrierJump, not FSDJump. It must move the
current system (found 2026-10-16: the app still showed Ekono after Imperial
Senator jumped to HIP 80311, and the EDDN CarrierJump was dropped)."""
from edc.core.eddn_publisher import build_message
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def test_carrier_jump_moves_current_system(tmp_path):
    eng = EventEngine(GameState(), tmp_path)
    eng.process({"timestamp": "2026-10-16T16:00:00Z", "event": "Location", "StarSystem": "Ekono",
                 "SystemAddress": 3205949786483, "StarPos": [1.0, 2.0, 3.0]})
    jump = {"timestamp": "2026-10-16T16:57:14Z", "event": "CarrierJump", "Docked": True, "StationName": "EUWC",
            "StationType": "FleetCarrier", "MarketID": 3713180160, "StarSystem": "HIP 80311",
            "SystemAddress": 182292859283, "StarPos": [59.65625, 113.375, 403.71875],
            "Factions": [{"Name": "Elite United Worlds", "Influence": 0.6}]}
    st, _ = eng.process(jump)
    assert (st.system, st.system_address) == ("HIP 80311", 182292859283)
    assert st.factions[0]["Name"] == "Elite United Worlds"
    assert build_message(jump, st.system, (st.system_x, st.system_y, st.system_z), st.system_address)
