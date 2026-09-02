"""EddnPowerPlayWorker._maybe_emit_body_mining_signal() -- extracts
Surface Mining's Planetary Mining Location signal count from a live
fssbodysignals/1 message body (other commanders' sightings), same
pattern as _maybe_emit_res_signal for fsssignaldiscovered/1."""
from edc.core.eddn_listener import EddnPowerPlayWorker


def _msg(**overrides):
    m = {
        "SystemAddress": 1281804437875,
        "BodyName": "HR 8769 A 1",
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Count": 3},
        ],
    }
    m.update(overrides)
    return m


def test_emits_mining_signal_from_real_message():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_mining_signal_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_body_mining_signal(_msg())

    assert seen == [(1281804437875, "HR 8769 A 1", 6)]


def test_no_mining_signal_present_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_mining_signal_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_body_mining_signal(_msg(Signals=[{"Type": "$SAA_SignalType_Geological;", "Count": 3}]))

    assert seen == []


def test_missing_system_address_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_mining_signal_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["SystemAddress"]
    worker._maybe_emit_body_mining_signal(m)

    assert seen == []


def test_missing_body_name_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_mining_signal_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["BodyName"]
    worker._maybe_emit_body_mining_signal(m)

    assert seen == []
