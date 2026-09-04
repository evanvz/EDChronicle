"""Per-system state (bodies, signals, economy, combat contacts, ...) must
only clear on confirmed arrival (FSDJump/Location, gated on the system
actually changing) -- not on StartJump (engaging the FSD). A cancelled or
interrupted jump (interdiction, mass lock, damage during the charge-up,
manually aborting) never produces a follow-up FSDJump/Location for the
system you were already in, so clearing on StartJump previously wiped
real data for a system you never actually left. Real EventEngine, no
mocks, matching this repo's convention."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _scan_event(body_name="Test Body 1", system_address=12345):
    return {
        "event": "Scan", "ScanType": "Detailed", "BodyName": body_name,
        "BodyID": 1, "SystemAddress": system_address,
        "PlanetClass": "Rocky body", "Landable": True,
        "WasDiscovered": True, "WasMapped": False,
    }


def test_startjump_does_not_clear_bodies(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_scan_event())
    assert "Test Body 1" in engine.state.bodies

    engine.process({"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "Elsewhere", "StarClass": "K"})

    assert "Test Body 1" in engine.state.bodies


def test_startjump_sets_transit_preview_fields(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "Elsewhere", "StarClass": "K"})

    assert engine.state.system == "Elsewhere"
    assert engine.state.in_hyperspace is True
    assert engine.state.jump_star_class == "K"


def test_cancelled_jump_preserves_all_per_system_state(tmp_path):
    # Full real-world sequence: scan a body, engage FSD, jump gets
    # interrupted (no FSDJump ever follows) -- everything must survive.
    engine = _engine(tmp_path)
    engine.process(_scan_event())
    engine.process({
        "event": "SAASignalsFound", "BodyName": "Test Body 1", "BodyID": 1,
        "SystemAddress": 12345,
        "Signals": [{"Type": "$SAA_SignalType_Geological;", "Count": 3}],
        "Genuses": [],
    })
    engine.process({"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "Elsewhere", "StarClass": "K"})

    assert "Test Body 1" in engine.state.bodies
    assert engine.state.geo_signals.get("Test Body 1") == 3
    assert engine.state.resolved_body_ids  # entry star/body still resolved


def test_fsdjump_to_new_system_clears_bodies(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_scan_event(system_address=12345))
    assert "Test Body 1" in engine.state.bodies

    engine.process({
        "event": "FSDJump", "StarSystem": "New System", "SystemAddress": 99999,
        "StarPos": [1.0, 2.0, 3.0],
    })

    assert engine.state.bodies == {}
    assert engine.state.geo_signals == {}


def test_fsdjump_to_new_system_clears_combat_contacts(tmp_path):
    engine = _engine(tmp_path)
    engine.state.combat_contacts["Some Ship"] = {"placeholder": True}
    engine.state.combat_current_key = "Some Ship"

    engine.process({
        "event": "FSDJump", "StarSystem": "New System", "SystemAddress": 99999,
        "StarPos": [1.0, 2.0, 3.0],
    })

    assert engine.state.combat_contacts == {}
    assert engine.state.combat_current_key == ""


def test_fsdjump_to_same_system_does_not_clear_bodies(tmp_path):
    # Regression guard already established for resolved_body_ids (journal
    # replay after a disconnect can re-fire FSDJump for the current
    # system) -- must hold for the newly-added fields too.
    engine = _engine(tmp_path)
    engine.process({
        "event": "FSDJump", "StarSystem": "Same System", "SystemAddress": 12345,
        "StarPos": [1.0, 2.0, 3.0],
    })
    engine.process(_scan_event(system_address=12345))
    assert "Test Body 1" in engine.state.bodies

    engine.process({
        "event": "FSDJump", "StarSystem": "Same System", "SystemAddress": 12345,
        "StarPos": [1.0, 2.0, 3.0],
    })

    assert "Test Body 1" in engine.state.bodies


def test_full_successful_jump_sequence_clears_exactly_once(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_scan_event(system_address=12345))
    assert "Test Body 1" in engine.state.bodies

    engine.process({"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "New System", "StarClass": "K"})
    assert "Test Body 1" in engine.state.bodies  # still intact mid-transit

    engine.process({
        "event": "FSDJump", "StarSystem": "New System", "SystemAddress": 99999,
        "StarPos": [1.0, 2.0, 3.0],
    })
    assert engine.state.bodies == {}  # cleared on confirmed arrival
    assert engine.state.in_hyperspace is False
