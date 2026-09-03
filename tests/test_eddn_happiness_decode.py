"""_decode_happiness() -- EDDN's journal/1 schema strips every
"_Localised$" key from Factions[] entries before publish (confirmed
against the schema's patternProperties rule), so Happiness_Localised
never survives onto the wire, only the raw internal Happiness token
does. Confirmed live: an eddn-sourced faction_snapshots row stored
"$Faction_HappinessBand3;" verbatim instead of "Discontented"."""
from edc.core.eddn_market import _decode_happiness, EddnMarketCache


def test_decodes_raw_happiness_token_when_localised_missing():
    faction = {"Name": "Test Faction", "Happiness": "$Faction_HappinessBand3;"}
    result = _decode_happiness(faction)
    assert result["Happiness_Localised"] == "Discontented"


def test_all_five_bands_decode():
    expected = {
        "$Faction_HappinessBand1;": "Elated",
        "$Faction_HappinessBand2;": "Happy",
        "$Faction_HappinessBand3;": "Discontented",
        "$Faction_HappinessBand4;": "Unhappy",
        "$Faction_HappinessBand5;": "Despondent",
    }
    for token, label in expected.items():
        result = _decode_happiness({"Happiness": token})
        assert result["Happiness_Localised"] == label


def test_does_not_override_existing_localised_value():
    faction = {"Happiness": "$Faction_HappinessBand3;", "Happiness_Localised": "Happy"}
    result = _decode_happiness(faction)
    assert result["Happiness_Localised"] == "Happy"


def test_unknown_token_left_untouched():
    faction = {"Happiness": "$SomeFutureBand_Name;"}
    result = _decode_happiness(faction)
    assert "Happiness_Localised" not in result


def test_missing_happiness_field_untouched():
    faction = {"Name": "Test Faction"}
    result = _decode_happiness(faction)
    assert result == faction


def test_does_not_mutate_input_dict():
    faction = {"Happiness": "$Faction_HappinessBand2;"}
    _decode_happiness(faction)
    assert "Happiness_Localised" not in faction


def test_on_faction_seen_buffers_decoded_happiness():
    cache = EddnMarketCache(repo=None)
    faction = {"Name": "Test Faction", "Happiness": "$Faction_HappinessBand3;"}
    cache.on_faction_seen(1, "Sol", faction, True, "2026-09-03T00:00:00Z")

    system_name, buffered_faction, is_controlling, timestamp = cache._faction_buffer[1]
    assert buffered_faction["Happiness_Localised"] == "Discontented"
