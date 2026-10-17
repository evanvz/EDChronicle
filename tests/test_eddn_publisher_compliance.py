"""EDDN Developers.md compliance -- two gaps found auditing our publisher
against the actual spec doc:

1. horizons/odyssey previously defaulted to True in EddnPublisher.__init__,
   sent on every outgoing message even before a real LoadGame event had
   been observed this session. The spec is explicit: "if you cannot
   determine a value do not include that key at all" -- not even False.
   Now None (unknown) until LoadGame sets a real bool, and the key is
   omitted entirely from the message while unknown.

2. build_message() augmented StarSystem/StarPos/SystemAddress from our
   tracked current-system state without cross-checking that the raw
   event's own identifiers (where present) actually agree first. The
   spec requires dropping the message entirely on a mismatch, to guard
   against a known journal-writing gap leaving tracked state one system
   behind the event being processed."""
from edc.core.eddn_publisher import EddnPublisher, build_message


# --- horizons/odyssey omitted until known ---

def test_horizons_odyssey_omitted_before_loadgame_observed():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})

    msg = {}
    pub._apply_horizons_odyssey(msg)

    assert "horizons" not in msg
    assert "odyssey" not in msg


def test_horizons_odyssey_set_after_loadgame_observed():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "Horizons": True, "Odyssey": False})

    msg = {}
    pub._apply_horizons_odyssey(msg)

    assert msg["horizons"] is True
    assert msg["odyssey"] is False


def test_odyssey_omitted_when_loadgame_lacks_the_key():
    # Real 3.8 Horizons client behavior per EDDN docs: LoadGame has
    # Horizons but no Odyssey key at all -- must stay omitted, not False.
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "Horizons": True})

    msg = {}
    pub._apply_horizons_odyssey(msg)

    assert msg["horizons"] is True
    assert "odyssey" not in msg


def test_fileheader_odyssey_flag_does_not_set_publisher_odyssey():
    # Fileheader's Odyssey flag means "4.0 client", not "Odyssey expansion
    # owned" -- must not be treated as the LoadGame-only source of truth.
    pub = EddnPublisher()
    pub.observe({"event": "Fileheader", "gameversion": "4.0.0.1450", "build": "r1", "odyssey": True})

    msg = {}
    pub._apply_horizons_odyssey(msg)

    assert "odyssey" not in msg


# --- build_message() SystemAddress/StarSystem cross-check ---

_STAR_POS = (1.0, 2.0, 3.0)


def test_mismatched_system_address_drops_message():
    event = {"event": "Docked", "SystemAddress": 111, "MarketID": 1}
    msg = build_message(event, "Tracked System", _STAR_POS, 222)
    assert msg is None


def test_matching_system_address_augments_normally():
    event = {"event": "Docked", "SystemAddress": 111, "MarketID": 1}
    msg = build_message(event, "Tracked System", _STAR_POS, 111)
    assert msg is not None
    assert msg["StarSystem"] == "Tracked System"
    assert msg["StarPos"] == [1.0, 2.0, 3.0]


def test_mismatched_star_system_name_drops_message():
    event = {"event": "Docked", "StarSystem": "Real System", "MarketID": 1}
    msg = build_message(event, "Wrong Tracked System", _STAR_POS, 111)
    assert msg is None


def test_matching_star_system_name_augments_system_address():
    event = {"event": "Docked", "StarSystem": "Real System", "MarketID": 1}
    msg = build_message(event, "Real System", _STAR_POS, 111)
    assert msg is not None
    assert msg["SystemAddress"] == 111


def test_event_with_no_identifiers_at_all_still_gets_augmented():
    event = {"event": "Docked", "MarketID": 1}
    msg = build_message(event, "Tracked System", _STAR_POS, 111)
    assert msg is not None
    assert msg["StarSystem"] == "Tracked System"
    assert msg["SystemAddress"] == 111


def test_event_with_all_identifiers_already_present_and_matching():
    event = {
        "event": "Docked", "MarketID": 1,
        "StarSystem": "Real System", "StarPos": [1.0, 2.0, 3.0], "SystemAddress": 111,
    }
    msg = build_message(event, "Real System", _STAR_POS, 111)
    assert msg is not None
    assert msg["StarSystem"] == "Real System"


# --- found by eddnvalid.weslocke.com (2026-10-17): the real publish path ---

def _published(pub, event, system="Sol", pos=(0.0, 0.0, 0.0), addr=10477373803):
    pub.maybe_publish(event, system, pos, addr)
    return pub._queue.get_nowait()


def _pub():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "Horizons": True, "Odyssey": True})
    return pub


def test_journal_messages_carry_horizons_odyssey():
    payload = _published(_pub(), {"timestamp": "2026-10-17T10:00:00Z", "event": "FSDJump",
                                  "StarSystem": "Sol", "SystemAddress": 10477373803, "StarPos": [0, 0, 0]})
    assert payload["$schemaRef"].endswith("/journal/1")
    assert payload["message"]["horizons"] is True and payload["message"]["odyssey"] is True


def test_codex_entry_goes_to_codexentry_schema():
    evt = {"timestamp": "2026-10-17T10:00:00Z", "event": "CodexEntry", "EntryID": 2100401,
           "Name": "$Codex_Ent_Stratum_02_F_Name;", "Name_Localised": "Stratum Excutitus - Green",
           "SubCategory": "$Codex_SubCategory_Organic_Structures;", "Category": "$Codex_Category_Biology;",
           "Region": "$Codex_RegionName_18;", "System": "Sol", "SystemAddress": 10477373803, "BodyID": 4,
           "Latitude": 1.5, "Longitude": -2.5, "IsNewEntry": True, "NewTraitsDiscovered": False, "VoucherAmount": 2500}
    payload = _published(_pub(), evt)
    msg = payload["message"]
    assert payload["$schemaRef"] == "https://eddn.edcd.io/schemas/codexentry/1"
    assert msg["StarPos"] == [0.0, 0.0, 0.0] and msg["horizons"] is True
    assert msg["Latitude"] == 1.5 and msg["VoucherAmount"] == 2500                      # allowed on codexentry
    for gone in ("IsNewEntry", "NewTraitsDiscovered", "Name_Localised", "BodyID"):
        assert gone not in msg


def test_codex_entry_for_another_system_is_dropped():
    pub = _pub()
    pub.maybe_publish({"timestamp": "2026-10-17T10:00:00Z", "event": "CodexEntry", "EntryID": 1,
                       "System": "Elsewhere", "SystemAddress": 42}, "Sol", (0.0, 0.0, 0.0), 10477373803)
    assert pub._queue.empty()


def test_watcher_replays_session_events_before_the_last_jump(tmp_path):
    """Startup replays only the newest system; LoadGame/Loadout etc. from
    earlier in the file must come first (2026-10-17: cargo unknown, CMDR ?)."""
    import json
    from edc.core.journal_watcher import JournalWatcher
    ev = [{"timestamp": "2026-10-17T09:46:00Z", "event": "Commander", "Name": "B0B R0GERS"},
          {"timestamp": "2026-10-17T09:46:01Z", "event": "LoadGame", "Horizons": True, "Odyssey": True},
          {"timestamp": "2026-10-17T10:29:46Z", "event": "Loadout", "Ship": "panthermkii", "CargoCapacity": 1218},
          {"timestamp": "2026-10-17T11:20:02Z", "event": "Loadout", "Ship": "krait_mkii", "CargoCapacity": 16},
          {"timestamp": "2026-10-17T11:40:00Z", "event": "FSDJump", "StarSystem": "ICZ VE-Q b5-4"},
          {"timestamp": "2026-10-17T11:41:00Z", "event": "Music"}]
    j = tmp_path / "Journal.2026-10-17T094611.01.log"
    j.write_text("\n".join(json.dumps(e, separators=(",", ":")) for e in ev) + "\n")
    w = JournalWatcher.__new__(JournalWatcher)
    seen = []
    w.event_received = type("S", (), {"emit": staticmethod(seen.append)})()
    w.status = type("S", (), {"emit": staticmethod(lambda *_: None)})()
    w._current_file, w._fp = j, j.open("r", encoding="utf-8")
    w._bootstrap_newest_system()
    w._fp.close()
    assert [e["event"] for e in seen] == ["Commander", "LoadGame", "Loadout", "FSDJump", "Music"]
    assert seen[2]["CargoCapacity"] == 16


def test_identical_journal_message_sent_once():
    """The game writes some arrival-star AutoScans twice, identical down to the
    timestamp (Journal.2026-10-17, 4 cases); eddnvalid counted the repeat."""
    pub = _pub()
    scan = {"timestamp": "2026-10-17T10:33:17Z", "event": "Scan", "ScanType": "AutoScan", "BodyName": "Sol A",
            "BodyID": 1, "StarSystem": "Sol", "SystemAddress": 10477373803, "StarPos": [0, 0, 0], "StarType": "G"}
    pub.maybe_publish(scan, "Sol", (0.0, 0.0, 0.0), 10477373803)
    pub.maybe_publish(dict(scan), "Sol", (0.0, 0.0, 0.0), 10477373803)
    pub.maybe_publish({**scan, "timestamp": "2026-10-17T10:40:00Z"}, "Sol", (0.0, 0.0, 0.0), 10477373803)  # a real rescan
    assert pub._queue.qsize() == 2


def test_one_version_everywhere():
    from edc.core import bgs_tick, eddn_publisher
    from edc.version import APP_VERSION
    assert eddn_publisher._SOFTWARE_VERSION == APP_VERSION == "1.0.2"
    assert bgs_tick._USER_AGENT.startswith("EDChronicle/1.0.2 ")
