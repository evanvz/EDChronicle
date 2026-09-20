"""MainWindow._announce_loaded_system_bodies()'s "N high value planets"
TTS callout -- confirmed live: fired for a ship with no Detailed Surface
Scanner fitted at all, nothing to actually act on the callout with. Same
"unknown vs confirmed absent" posture as the ship_has_weapons/enemy-alert
caveat elsewhere: suppress only on a confirmed False (a real Loadout
already seen this session with no DSS), not on None (no Loadout event
yet). Fake-self/SimpleNamespace pattern already established for
MainWindow method tests."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.ui.main_window import MainWindow


def _fake_self(ship_has_dss, hv_body=True):
    bodies = {}
    if hv_body:
        bodies["Body A"] = {"EstimatedValue": 10_000_000, "DSSMapped": False}
    return SimpleNamespace(
        cfg=SimpleNamespace(tts_enabled=True, tts_events={"Scan": True}, min_planet_value_100k=5),
        state=SimpleNamespace(bodies=bodies, ship_has_dss=ship_has_dss),
        tts=SimpleNamespace(speak=MagicMock()),
    )


def test_callout_suppressed_when_no_dss_fitted():
    fake_self = _fake_self(ship_has_dss=False)
    MainWindow._announce_loaded_system_bodies(fake_self)
    fake_self.tts.speak.assert_not_called()


def test_callout_fires_when_dss_fitted():
    fake_self = _fake_self(ship_has_dss=True)
    MainWindow._announce_loaded_system_bodies(fake_self)
    fake_self.tts.speak.assert_called_once()


def test_callout_fires_when_dss_unknown():
    # No Loadout event seen yet this session -- must not be silently
    # suppressed forever just because we don't know yet.
    fake_self = _fake_self(ship_has_dss=None)
    MainWindow._announce_loaded_system_bodies(fake_self)
    fake_self.tts.speak.assert_called_once()


def test_no_high_value_bodies_never_speaks_regardless_of_dss():
    fake_self = _fake_self(ship_has_dss=True, hv_body=False)
    MainWindow._announce_loaded_system_bodies(fake_self)
    fake_self.tts.speak.assert_not_called()
