"""Tests for EddnMarketCache.on_fcmaterials_message() -- Items[].Name
arrives '$symbol_name;'-wrapped (confirmed against a real captured
fcmaterials_journal/1 sample embedded in EDMarketConnector's eddn.py),
not bare, so it must be unwrapped to match this codebase's bare-lowercase
material symbol convention (see settings/odyssey_engineering.json /
settings/engineering_blueprints.json) before being buffered."""
from edc.core.eddn_market import EddnMarketCache


def _msg(items):
    return {
        "timestamp": "2026-08-12T10:00:00Z",
        "event": "FCMaterials",
        "MarketID": 3705242624,
        "CarrierID": "ABC-123",
        "CarrierName": "Test Carrier",
        "Items": items,
    }


def _item(name, **overrides):
    it = {"id": 128961533, "Name": name, "Name_Localised": "Encrypted Memory Chip",
          "Price": 500, "Stock": 0, "Demand": 5}
    it.update(overrides)
    return it


def test_dollar_wrapped_name_is_unwrapped_to_bare_lowercase_symbol():
    cache = EddnMarketCache(repo=None)
    cache.on_fcmaterials_message(_msg([_item("$graphene_name;")]))

    coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, mining_signals, system_profiles = cache.pop_buffers()
    assert len(fcmaterials) == 1
    market_id, symbol = fcmaterials[0][0], fcmaterials[0][1]
    assert market_id == 3705242624
    assert symbol == "graphene"


def test_uppercase_wrapped_name_is_lowercased():
    cache = EddnMarketCache(repo=None)
    cache.on_fcmaterials_message(_msg([_item("$GRAPHENE_name;")]))

    _, _, _, _, _, fcmaterials, _, _, _, _, _ = cache.pop_buffers()
    assert fcmaterials[0][1] == "graphene"


def test_empty_name_after_unwrap_is_skipped():
    cache = EddnMarketCache(repo=None)
    cache.on_fcmaterials_message(_msg([_item("")]))

    _, _, _, _, _, fcmaterials, _, _, _, _, _ = cache.pop_buffers()
    assert fcmaterials == []
