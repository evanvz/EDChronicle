"""Tests for eddn_listener.py's BGS-status/RES-signal message parsing --
pure functions, no ZMQ/network needed."""
from edc.core.eddn_listener import _extract_bgs_status, _extract_res_tiers


def test_extract_bgs_status_returns_war_conflicts_and_multistate_factions():
    msg = {
        "SystemAddress": 12345,
        "StarSystem": "HIP 22052",
        "Conflicts": [
            {"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 2}, "Faction2": {"Name": "B", "WonDays": 1}},
            {"WarType": "election", "Faction1": {"Name": "X"}, "Faction2": {"Name": "Y"}},
        ],
        "Factions": [
            {"Name": "A", "ActiveStates": [{"State": "War"}]},
            {"Name": "Z", "ActiveStates": [], "PendingStates": [], "RecoveringStates": []},
        ],
    }
    conflicts, factions = _extract_bgs_status(msg)
    assert len(conflicts) == 1 and conflicts[0]["WarType"] == "war"
    assert len(factions) == 1 and factions[0]["Name"] == "A"


def test_extract_bgs_status_empty_when_nothing_relevant():
    msg = {"SystemAddress": 1, "StarSystem": "Sol", "Conflicts": [], "Factions": [{"Name": "A"}]}
    conflicts, factions = _extract_bgs_status(msg)
    assert conflicts == [] and factions == []


def test_extract_res_tiers_from_signals_array():
    msg = {
        "SystemAddress": 12345,
        "StarSystem": "HIP 22052",
        "signals": [
            {"SignalName_Localised": "Resource Extraction Site [Hazardous]", "SignalType": "ResourceExtraction"},
            {"SignalName_Localised": "Resource Extraction Site [Low]", "SignalType": "ResourceExtraction"},
            {"SignalName_Localised": "Nav Beacon", "SignalType": "NavBeacon"},
        ],
    }
    tiers = _extract_res_tiers(msg)
    assert tiers == ["Hazardous", "Low"]


def test_extract_res_tiers_empty_when_no_res_signals():
    msg = {"SystemAddress": 1, "StarSystem": "Sol", "signals": [{"SignalName": "Nav Beacon", "SignalType": "NavBeacon"}]}
    assert _extract_res_tiers(msg) == []
