"""Tests for build_commodity_message() -- transforms a Market.json dict
into an EDDN commodity/3-compliant message body. Elision/rename rules
verified against EDDN's own commodity-README.md and a real Market.json
sample (see docs/superpowers/specs/2026-08-11-eddn-commodity-publish-design.md)."""
from unittest.mock import Mock, patch

from edc.core.eddn_publisher import build_commodity_message, EddnPublisher, _COMMODITY_SCHEMA_REF


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


def test_maybe_publish_commodity_queues_compliant_envelope():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({
        "event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000",
        "Horizons": False, "Odyssey": True,
    })

    pub.maybe_publish_commodity(_market([_item()]))

    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == _COMMODITY_SCHEMA_REF
    assert payload["header"]["uploaderID"] == "CMDR Test"
    assert payload["header"]["softwareName"] == "EDChronicle"
    assert payload["header"]["gameversion"] == "4.0"
    assert payload["message"]["systemName"] == "Shinrarta Dezhra"
    assert payload["message"]["commodities"][0]["name"] == "platinum"
    assert payload["message"]["horizons"] is False
    assert payload["message"]["odyssey"] is True


def test_maybe_publish_commodity_skips_when_no_commander_known():
    pub = EddnPublisher()
    pub.maybe_publish_commodity(_market([_item()]))
    assert pub._queue.empty()


def test_maybe_publish_commodity_skips_invalid_market_data():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.maybe_publish_commodity({"not": "a valid market"})
    assert pub._queue.empty()


def _fake_response(status_code):
    resp = Mock()
    resp.status_code = status_code
    resp.text = "response body"
    return resp


def test_send_with_retry_retries_on_429_and_5xx():
    pub = EddnPublisher()
    for status in (429, 500, 503):
        with patch("edc.core.eddn_publisher.requests.post", return_value=_fake_response(status)), \
             patch("edc.core.eddn_publisher.threading.Timer") as mock_timer:
            pub._send_with_retry({"payload": "x"})
            assert mock_timer.called, f"expected retry timer for status {status}"


def test_send_with_retry_drops_permanent_4xx_rejection():
    pub = EddnPublisher()
    with patch("edc.core.eddn_publisher.requests.post", return_value=_fake_response(400)), \
         patch("edc.core.eddn_publisher.threading.Timer") as mock_timer:
        pub._send_with_retry({"payload": "x"})
        assert not mock_timer.called


def test_item_with_non_int_price_is_dropped_but_others_survive():
    bad = _item(name="$aluminium_name;", BuyPrice="not a number")
    msg = build_commodity_message(_market([_item(), bad]))
    names = [c["name"] for c in msg["commodities"]]
    assert names == ["platinum"]


def test_item_with_out_of_range_bracket_is_dropped():
    bad = _item(name="$aluminium_name;", StockBracket=7)
    msg = build_commodity_message(_market([_item(), bad]))
    names = [c["name"] for c in msg["commodities"]]
    assert names == ["platinum"]


def test_item_with_bool_price_is_dropped():
    bad = _item(name="$aluminium_name;", BuyPrice=True)
    msg = build_commodity_message(_market([_item(), bad]))
    names = [c["name"] for c in msg["commodities"]]
    assert names == ["platinum"]


def test_item_with_bool_bracket_is_dropped():
    bad = _item(name="$aluminium_name;", DemandBracket=True)
    msg = build_commodity_message(_market([_item(), bad]))
    names = [c["name"] for c in msg["commodities"]]
    assert names == ["platinum"]


def test_limpets_skipped_by_category_even_with_unexpected_symbol():
    # Category-substring check should catch a NonMarketable item even if
    # its symbol somehow didn't match the known "drones" case.
    limpets = _item(name="$somefuturelimpet_name;", Category="$MARKET_category_NonMarketable;")
    msg = build_commodity_message(_market([_item(), limpets]))
    names = [c["name"] for c in msg["commodities"]]
    assert "somefuturelimpet" not in names
    assert names == ["platinum"]


def test_maybe_publish_commodity_skips_beta_build():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0 beta 1", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]))

    assert pub._queue.empty()


def test_docking_access_added_when_provided():
    msg = build_commodity_message(_market([_item()]), docking_access="all")
    assert msg["carrierDockingAccess"] == "all"


def test_docking_access_absent_when_not_provided():
    msg = build_commodity_message(_market([_item()]))
    assert "carrierDockingAccess" not in msg


def test_docking_access_absent_when_empty_string():
    msg = build_commodity_message(_market([_item()]), docking_access="")
    assert "carrierDockingAccess" not in msg


def test_maybe_publish_commodity_threads_docking_access_into_queued_message():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]), docking_access="friends")

    payload = pub._queue.get_nowait()
    assert payload["message"]["carrierDockingAccess"] == "friends"


def test_maybe_publish_commodity_omits_docking_access_key_when_not_given():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]))

    payload = pub._queue.get_nowait()
    assert "carrierDockingAccess" not in payload["message"]
