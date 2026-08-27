"""Tests for EddnMarketCache.on_outfitting_message()/on_shipyard_message()
against EDDN's REAL wire format -- confirmed against EDCD/EDDN's published
schemas (schemas/outfitting-v2.0.json, schemas/shipyard-v2.0.json): both
"modules" and "ships" are arrays of plain symbol strings (e.g.
"Hpt_ChaffLauncher_Tiny"), not objects with a ModuleName/ShipType key. A
prior isinstance(m, dict) check meant every real EDDN message silently
produced zero buffered rows -- no test existed to catch it, since none of
the (bulky, dict-shaped) inputs anyone had used to exercise this by hand
matched the real schema either."""
from edc.core.eddn_market import EddnMarketCache


def _cache():
    return EddnMarketCache(repo=None)


# --- on_outfitting_message ---

def test_real_eddn_outfitting_message_is_buffered():
    cache = _cache()
    cache.on_outfitting_message({
        "marketId": 128666762,
        "stationName": "Jameson Memorial",
        "systemName": "Shinrarta Dezhra",
        "modules": ["Hpt_ChaffLauncher_Tiny", "Int_Engine_Size3_Class5_Fast"],
        "timestamp": "2026-08-23T10:00:00Z",
    })
    buffered = cache.pop_buffers()[9]  # outfitting is the 10th element
    assert len(buffered) == 1
    market_id, station_name, system_name, modules, timestamp = buffered[0]
    assert market_id == 128666762
    assert modules == ["Hpt_ChaffLauncher_Tiny", "Int_Engine_Size3_Class5_Fast"]


def test_outfitting_message_with_dict_items_is_not_silently_swallowed():
    # Regression guard for the exact bug: a wrongly-dict-shaped list must
    # not be misread as valid data either.
    cache = _cache()
    cache.on_outfitting_message({
        "marketId": 1, "stationName": "X", "systemName": "Y",
        "modules": [{"ModuleName": "Hpt_ChaffLauncher_Tiny"}],
        "timestamp": "2026-08-23T10:00:00Z",
    })
    assert cache.pop_buffers()[9] == []


def test_outfitting_message_missing_market_id_is_ignored():
    cache = _cache()
    cache.on_outfitting_message({"modules": ["Hpt_ChaffLauncher_Tiny"], "timestamp": "2026-08-23T10:00:00Z"})
    assert cache.pop_buffers()[9] == []


def test_outfitting_message_with_no_modules_is_ignored():
    cache = _cache()
    cache.on_outfitting_message({"marketId": 1, "modules": [], "timestamp": "2026-08-23T10:00:00Z"})
    assert cache.pop_buffers()[9] == []


# --- on_shipyard_message ---

def test_real_eddn_shipyard_message_is_buffered():
    cache = _cache()
    cache.on_shipyard_message({
        "marketId": 128666762,
        "stationName": "Jameson Memorial",
        "systemName": "Shinrarta Dezhra",
        "ships": ["Anaconda", "CobraMkIII", "FerDeLance"],
        "timestamp": "2026-08-23T10:00:00Z",
    })
    buffered = cache.pop_buffers()[10]  # shipyard is the 11th element
    assert len(buffered) == 1
    market_id, station_name, system_name, ships, timestamp = buffered[0]
    assert market_id == 128666762
    assert ships == ["Anaconda", "CobraMkIII", "FerDeLance"]


def test_shipyard_message_with_dict_items_is_not_silently_swallowed():
    cache = _cache()
    cache.on_shipyard_message({
        "marketId": 1, "ships": [{"ShipType": "Anaconda"}], "timestamp": "2026-08-23T10:00:00Z",
    })
    assert cache.pop_buffers()[10] == []
