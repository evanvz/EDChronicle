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
