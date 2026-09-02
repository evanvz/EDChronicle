"""EddnPowerPlayWorker._maybe_emit_system_profile() -- extracts real
SystemEconomy/SystemSecondEconomy/SystemGovernment/SystemSecurity/
Population/SystemAllegiance from a live journal/1 FSDJump/Location/
CarrierJump message (other commanders' sightings). Confirmed live: EDDN's
journal-v1.0 schema has additionalProperties:true at message level and
doesn't disallow these fields, so real uploaders pass them through
untouched -- verified against the user's own real FSDJump event."""
from edc.core.eddn_listener import EddnPowerPlayWorker


def _msg(**overrides):
    m = {
        "SystemAddress": 3205949786483,
        "StarSystem": "Ekono",
        "SystemAllegiance": "Empire",
        "SystemEconomy": "$economy_Agri;",
        "SystemSecondEconomy": "$economy_HighTech;",
        "SystemGovernment": "$government_Patronage;",
        "SystemSecurity": "$SYSTEM_SECURITY_medium;",
        "Population": 2474591197,
        "timestamp": "2026-09-02T15:30:25Z",
    }
    m.update(overrides)
    return m


def test_emits_profile_from_real_message():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.system_profile_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_system_profile(_msg(), "2026-09-02T15:30:25Z")

    assert len(seen) == 1
    system_address, star_system, profile, timestamp = seen[0]
    assert system_address == 3205949786483
    assert star_system == "Ekono"
    assert profile == {
        "economy": "$economy_Agri;",
        "second_economy": "$economy_HighTech;",
        "government": "$government_Patronage;",
        "security": "$SYSTEM_SECURITY_medium;",
        "population": 2474591197,
        "allegiance": "Empire",
    }


def test_missing_system_economy_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.system_profile_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["SystemEconomy"]
    worker._maybe_emit_system_profile(m, "2026-09-02T15:30:25Z")

    assert seen == []


def test_missing_system_address_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.system_profile_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["SystemAddress"]
    worker._maybe_emit_system_profile(m, "2026-09-02T15:30:25Z")

    assert seen == []
