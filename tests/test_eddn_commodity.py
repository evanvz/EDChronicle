"""Tests for build_commodity_message() -- transforms a Market.json dict
into an EDDN commodity/3-compliant message body. Elision/rename rules
verified against EDDN's own commodity-README.md and a real Market.json
sample (see docs/superpowers/specs/2026-08-11-eddn-commodity-publish-design.md)."""
from edc.core.eddn_publisher import build_commodity_message


def _market(items):
    return {
        "timestamp": "2026-08-11T10:00:00Z",
        "event": "Market",
        "MarketID": 128049152,
        "StationName": "Jameson Memorial",
        "StationType": "Orbis",
        "StarSystem": "Shinrarta Dezhra",
        "Items": items,
    }


def _item(name="$platinum_name;", **overrides):
    it = {
        "id": 128049152,
        "Name": name,
        "Name_Localised": "Platinum",
        "Category": "$MARKET_category_metals;",
        "Category_Localised": "Metals",
        "BuyPrice": 0,
        "SellPrice": 59006,
        "MeanPrice": 55505,
        "StockBracket": 0,
        "DemandBracket": 3,
        "Stock": 0,
        "Demand": 33966,
        "Consumer": True,
        "Producer": False,
        "Rare": False,
    }
    it.update(overrides)
    return it


def test_valid_market_produces_compliant_message():
    msg = build_commodity_message(_market([_item()]))
    assert msg == {
        "systemName": "Shinrarta Dezhra",
        "stationName": "Jameson Memorial",
        "marketId": 128049152,
        "timestamp": "2026-08-11T10:00:00Z",
        "commodities": [{
            "name": "platinum",
            "meanPrice": 55505,
            "buyPrice": 0,
            "stock": 0,
            "stockBracket": 0,
            "sellPrice": 59006,
            "demand": 33966,
            "demandBracket": 3,
        }],
    }


def test_name_dollar_wrapper_is_stripped():
    msg = build_commodity_message(_market([_item(name="$aluminium_name;")]))
    assert msg["commodities"][0]["name"] == "aluminium"


def test_limpets_are_skipped():
    limpets = _item(
        name="$drones_name;",
        Category="$MARKET_category_nonmarketable;",
        Category_Localised="Non-marketable",
    )
    msg = build_commodity_message(_market([_item(), limpets]))
    names = [c["name"] for c in msg["commodities"]]
    assert "drones" not in names
    assert names == ["platinum"]


def test_producer_rare_id_category_are_dropped_from_item():
    msg = build_commodity_message(_market([_item()]))
    commodity = msg["commodities"][0]
    for forbidden_key in ("Producer", "Rare", "id", "Category", "Category_Localised"):
        assert forbidden_key not in commodity


def test_station_type_is_dropped_from_message():
    msg = build_commodity_message(_market([_item()]))
    assert "StationType" not in msg
    assert "stationType" not in msg


def test_economies_and_prohibited_are_never_present():
    msg = build_commodity_message(_market([_item()]))
    assert "economies" not in msg
    assert "prohibited" not in msg


def test_missing_required_field_returns_none():
    data = _market([_item()])
    del data["MarketID"]
    assert build_commodity_message(data) is None


def test_no_tradeable_commodities_returns_none():
    limpets = _item(name="$drones_name;", Category="$MARKET_category_nonmarketable;")
    assert build_commodity_message(_market([limpets])) is None


def test_not_a_dict_returns_none():
    assert build_commodity_message(None) is None
    assert build_commodity_message([]) is None


def test_empty_items_returns_none():
    assert build_commodity_message(_market([])) is None
