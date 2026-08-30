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


def test_lagrange_platform_not_misclassified_as_phenomena():
    # Real station, not a phenomenon -- confirmed live at HIP 11645. Falls
    # through to the name-heuristic fallback when signal_type/is_station
    # aren't set (e.g. an FSS-only sighting), so the bare "lagrange"
    # keyword previously caught it by name alone.
    result = EventEngine._classify_system_signal(
        None, "Lagrange Platform", "", None, None,
    )
    assert result != "Phenomena"


def test_compromised_navigation_beacon_classified_distinctly():
    # Shares SignalType="NavBeacon" with a plain Nav Beacon -- only the
    # localised name distinguishes it (confirmed live via real journal
    # data). No security response there, a real combat/PP-merit spot a
    # plain Nav Beacon isn't.
    result = EventEngine._classify_system_signal(
        None, "Compromised Navigation Beacon", "", None, "NavBeacon",
    )
    assert result == "CompromisedNavBeacon"


def test_plain_nav_beacon_still_classified_as_navbeacon():
    result = EventEngine._classify_system_signal(
        None, "Nav Beacon", "", None, "NavBeacon",
    )
    assert result == "NavBeacon"


def test_lagrange_cloud_still_classified_as_phenomena():
    # The actual Notable Stellar Phenomena type "lagrange" was added for --
    # still caught via the "cloud" keyword alone.
    result = EventEngine._classify_system_signal(
        None, "Lagrange Cloud", "", None, None,
    )
    assert result == "Phenomena"
