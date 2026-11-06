"""codexentry-README "BodyID and BodyName": BodyName comes from Status.json, and
BodyID only when the journal's tracked body has the same name. Otherwise the keys
are left out, never sent empty."""
from edc.core.eddn_publisher import EddnPublisher

BODY, OTHER = "Bestia A 2 a", "Bestia A 2 b"


def _pub():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR", "Horizons": True, "Odyssey": True,
                 "gameversion": "4.4", "build": "r1"})
    return pub


def _codex(pub):
    pub.maybe_publish({"timestamp": "2026-11-06T10:00:00Z", "event": "CodexEntry", "EntryID": 2100205,
                       "System": "Sol", "SystemAddress": 1, "BodyID": 99, "Latitude": 1.5, "Longitude": 2.5},
                      "Sol", (0.0, 0.0, 0.0), 1)
    return pub._queue.get_nowait()["message"]


def _approach(body=BODY, body_id=15):
    return {"event": "ApproachBody", "Body": body, "BodyID": body_id}


def _status(body=BODY):
    return {"event": "Status", "Flags": 1, **({"BodyName": body} if body else {})}


def test_status_and_journal_agree_sends_both():
    pub = _pub()
    pub.observe(_approach())
    pub.observe(_status())
    msg = _codex(pub)
    assert msg["BodyName"] == BODY and msg["BodyID"] == 15


def test_binary_companion_sends_name_without_id():
    pub = _pub()
    pub.observe(_approach(OTHER, 16))
    pub.observe(_status())
    msg = _codex(pub)
    assert msg["BodyName"] == BODY and "BodyID" not in msg


def test_no_status_body_sends_neither():
    pub = _pub()
    pub.observe(_approach())
    pub.observe(_status(None))
    msg = _codex(pub)
    assert "BodyName" not in msg and "BodyID" not in msg


def test_status_body_clears_when_it_goes_away():
    pub = _pub()
    pub.observe(_approach())
    pub.observe(_status())
    pub.observe(_status(None))
    msg = _codex(pub)
    assert "BodyName" not in msg and "BodyID" not in msg


def test_location_covers_logging_in_already_there():
    pub = _pub()
    pub.observe({"event": "Location", "Body": BODY, "BodyID": 15, "BodyType": "Planet"})
    pub.observe(_status())
    assert _codex(pub)["BodyID"] == 15


def test_leavebody_and_fsdjump_clear_the_journal_body():
    for leaving in ({"event": "LeaveBody", "Body": BODY, "BodyID": 15}, {"event": "FSDJump", "Body": "Star", "BodyID": 0}):
        pub = _pub()
        pub.observe(_approach())
        pub.observe(leaving)
        pub.observe(_status())
        msg = _codex(pub)
        assert msg["BodyName"] == BODY and "BodyID" not in msg


def test_supercruise_keeps_the_journal_body():
    pub = _pub()
    pub.observe(_approach())
    pub.observe({"event": "SupercruiseEntry"})
    pub.observe(_status())
    assert _codex(pub)["BodyID"] == 15


def test_non_integer_id_is_left_out():
    pub = _pub()
    pub.observe(_approach(BODY, "15"))
    pub.observe(_status())
    assert "BodyID" not in _codex(pub)


def test_other_journal_messages_get_no_body_added():
    pub = _pub()
    pub.observe(_approach())
    pub.observe(_status())
    pub.maybe_publish({"timestamp": "2026-11-06T10:00:00Z", "event": "SAASignalsFound", "BodyName": "X", "BodyID": 3,
                       "SystemAddress": 1, "Signals": []}, "Sol", (0.0, 0.0, 0.0), 1)
    assert pub._queue.get_nowait()["message"]["BodyName"] == "X"
