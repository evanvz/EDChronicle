"""fsssignaldiscovered/1: contiguous FSSSignalDiscovered runs go out as one
message when another event arrives (fsssignaldiscovered-README "Batching")."""
from edc.core.eddn_publisher import EddnPublisher

SOL = ("Sol", (0.0, 0.0, 0.0), 10477373803)


def _sig(name, addr=10477373803, **kw):
    return {"timestamp": "2026-10-17T10:00:00Z", "event": "FSSSignalDiscovered", "SystemAddress": addr,
            "SignalName": name, **kw}


def _pub():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR T", "Horizons": True, "Odyssey": True})
    return pub


def test_run_is_sent_as_one_message_on_next_event():
    pub = _pub()
    for e in (_sig("EXPLORER-CLASS X2X-74M", IsStation=True),
              _sig("$USS;", SignalName_Localised="Unidentified signal source", USSType="$USS_Type_Salvage;",
                   TimeRemaining=900.5),
              _sig("$USS;", USSType="$USS_Type_MissionTarget;"),          # only useful to its own Cmdr
              _sig("Elsewhere", addr=42)):                                # failed location cross-check
        pub.batch_signals(e, *SOL)
    assert pub._queue.empty()
    pub.batch_signals({"event": "Music"}, *SOL)
    p = pub._queue.get_nowait()
    m = p["message"]
    assert p["$schemaRef"] == "https://eddn.edcd.io/schemas/fsssignaldiscovered/1"
    assert (m["StarSystem"], m["SystemAddress"], m["odyssey"]) == ("Sol", 10477373803, True)
    assert [s["SignalName"] for s in m["signals"]] == ["EXPLORER-CLASS X2X-74M", "$USS;"]
    assert m["signals"][1] == {"timestamp": "2026-10-17T10:00:00Z", "SignalName": "$USS;",
                               "USSType": "$USS_Type_Salvage;"}
    assert pub._queue.empty()


def test_signals_before_an_arrival_use_the_arrival_location():
    pub = _pub()
    pub.batch_signals(_sig("New carrier", addr=99), *SOL)                 # Odyssey: signals come first
    pub.batch_signals({"event": "FSDJump", "StarSystem": "Achenar", "StarPos": [67.5, -119.5, 24.8],
                       "SystemAddress": 99}, *SOL)
    assert pub._queue.get_nowait()["message"]["StarSystem"] == "Achenar"
