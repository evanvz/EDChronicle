"""EddnPowerPlayWorker._maybe_emit_body_signals() -- extracts whichever
known signal buckets (biological/geological/human/guardian/thargoid/
mining) are present in a live fssbodysignals/1 message body (other
commanders' sightings), same bucket keywords event_engine.py uses for
the commander's own live scans. Generalized from mining-only (Surface
Mining, Update 4.4 was the original motivation) to cover the other
types other commanders' sightings also carry for the same event."""
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


def test_emits_mining_and_geo_from_real_message():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_signals_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_body_signals(_msg())

    assert seen == [(1281804437875, "HR 8769 A 1", {"mining": 6, "geo": 3})]


def test_all_six_buckets_extracted():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_signals_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_body_signals(_msg(Signals=[
        {"Type": "$SAA_SignalType_Biological;", "Count": 4},
        {"Type": "$SAA_SignalType_Geological;", "Count": 3},
        {"Type": "$SAA_SignalType_Human;", "Count": 1},
        {"Type": "$SAA_SignalType_Guardian;", "Count": 2},
        {"Type": "$SAA_SignalType_Thargoid;", "Count": 5},
        {"Type": "$PlanetaryMiningLocation_Name;", "Count": 6},
    ]))

    assert seen == [(1281804437875, "HR 8769 A 1", {
        "bio": 4, "geo": 3, "human": 1, "guardian": 2, "thargoid": 5, "mining": 6,
    })]


def test_no_known_signal_present_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_signals_seen.connect(lambda *args: seen.append(args))

    worker._maybe_emit_body_signals(_msg(Signals=[{"Type": "$SomeFutureSignalType_Name;", "Count": 3}]))

    assert seen == []


def test_missing_system_address_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_signals_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["SystemAddress"]
    worker._maybe_emit_body_signals(m)

    assert seen == []


def test_missing_body_name_emits_nothing():
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_signals_seen.connect(lambda *args: seen.append(args))

    m = _msg()
    del m["BodyName"]
    worker._maybe_emit_body_signals(m)

    assert seen == []
