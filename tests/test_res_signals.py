"""Tests for res_tier_from_signal_name() -- pure function, no Qt needed."""
from edc.core.res_signals import res_tier_from_signal_name


def test_nominal_res_has_no_bracket():
    assert res_tier_from_signal_name("Resource Extraction Site") == "Nominal"


def test_low_res():
    assert res_tier_from_signal_name("Resource Extraction Site [Low]") == "Low"


def test_high_res():
    assert res_tier_from_signal_name("Resource Extraction Site [High]") == "High"


def test_hazardous_res():
    assert res_tier_from_signal_name("Resource Extraction Site [Hazardous]") == "Hazardous"


def test_non_res_signal_name_defaults_nominal():
    assert res_tier_from_signal_name("Nav Beacon") == "Nominal"


def test_non_string_input_defaults_nominal():
    assert res_tier_from_signal_name(None) == "Nominal"


def test_unresolved_raw_token_returns_unknown():
    assert res_tier_from_signal_name("$MULTIPLAYER_SCENARIO14_TITLE;") == "Unknown"
