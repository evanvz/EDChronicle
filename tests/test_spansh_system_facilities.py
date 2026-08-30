"""SpanshSystem.has_vista_genomics()/has_universal_cartographics() check
the station "services" array Spansh's API already returns per station
(previously discarded) -- needed to find a valid turn-in point for
exploration/exobiology PowerPlay data-recovery activities."""
from edc.core.spansh_client import SpanshSystem


def test_has_vista_genomics_true_when_present():
    sys_ = SpanshSystem(
        name="Test", distance=1.0, controlling_power="", pp_state="",
        station_services=["Dock", "Market", "Vista Genomics"],
    )
    assert sys_.has_vista_genomics() is True


def test_has_vista_genomics_false_when_absent():
    sys_ = SpanshSystem(
        name="Test", distance=1.0, controlling_power="", pp_state="",
        station_services=["Dock", "Market"],
    )
    assert sys_.has_vista_genomics() is False


def test_has_universal_cartographics_true_when_present():
    sys_ = SpanshSystem(
        name="Test", distance=1.0, controlling_power="", pp_state="",
        station_services=["Dock", "Universal Cartographics"],
    )
    assert sys_.has_universal_cartographics() is True


def test_has_universal_cartographics_false_when_absent():
    sys_ = SpanshSystem(
        name="Test", distance=1.0, controlling_power="", pp_state="",
        station_services=["Dock"],
    )
    assert sys_.has_universal_cartographics() is False


def test_no_stations_means_neither_service():
    sys_ = SpanshSystem(name="Test", distance=1.0, controlling_power="", pp_state="")
    assert sys_.has_vista_genomics() is False
    assert sys_.has_universal_cartographics() is False
