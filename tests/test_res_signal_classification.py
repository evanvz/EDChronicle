"""Tests for RES classification in EventEngine._classify_system_signal --
pure method (never touches self), called unbound so no GameState/
settings_base construction is needed. Matches tests/test_engage_risk.py's
"pure function, no Qt needed" structure."""
from edc.core.event_engine import EventEngine


def test_resource_extraction_signal_type_classified_as_res():
    result = EventEngine._classify_system_signal(
        None, "Resource Extraction Site [Hazardous]", "", None, "ResourceExtraction",
    )
    assert result == "RES"


def test_nominal_resource_extraction_signal_type_classified_as_res():
    result = EventEngine._classify_system_signal(
        None, "Resource Extraction Site", "", None, "ResourceExtraction",
    )
    assert result == "RES"


def test_nav_beacon_still_classified_separately_from_res():
    result = EventEngine._classify_system_signal(
        None, "Nav Beacon", "", None, "NavBeacon",
    )
    assert result == "NavBeacon"
