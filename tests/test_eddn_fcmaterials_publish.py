"""Tests for build_fcmaterials_message() and
EddnPublisher.maybe_publish_fcmaterials() -- transforms an FCMaterials.json
dict into an EDDN fcmaterials_journal/1-compliant message body. Schema
requirements (exact required fields, lowercase "id", additionalProperties:
false) verified directly against EDCD/EDDN's schema repo -- see
docs/superpowers/specs/2026-08-16-eddn-carrier-reciprocity-design.md."""
from edc.core.eddn_publisher import (
    build_fcmaterials_message, EddnPublisher, _FCMATERIALS_SCHEMA_REF,
)


def _fcmaterials(items):
    return {
        "timestamp": "2026-08-16T10:00:00Z",
        "event": "FCMaterials",
        "MarketID": 3705599744,
        "CarrierID": "K7X-83Z",
        "CarrierName": "TESTBED",
        "Items": items,
    }


def _fc_item(name="$graphene_name;", **overrides):
    it = {
        "id": 128924331,
        "Name": name,
        "Name_Localised": "Graphene",
        "Category": "$MARKET_category_manufactured;",
        "Category_Localised": "Manufactured",
        "Price": 1200,
        "Stock": 50,
        "Demand": 0,
    }
    it.update(overrides)
    return it


def test_valid_fcmaterials_produces_compliant_message():
    msg = build_fcmaterials_message(_fcmaterials([_fc_item()]))
    assert msg == {
        "timestamp": "2026-08-16T10:00:00Z",
        "event": "FCMaterials",
        "MarketID": 3705599744,
        "CarrierID": "K7X-83Z",
        "CarrierName": "TESTBED",
        "Items": [{
            "id": 128924331,
            "Name": "$graphene_name;",
            "Price": 1200,
            "Stock": 50,
            "Demand": 0,
        }],
    }


def test_name_localised_and_category_dropped_from_item():
    msg = build_fcmaterials_message(_fcmaterials([_fc_item()]))
    item = msg["Items"][0]
    for forbidden_key in ("Name_Localised", "Category", "Category_Localised"):
        assert forbidden_key not in item


def test_missing_market_id_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["MarketID"]
    assert build_fcmaterials_message(data) is None


def test_missing_carrier_name_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["CarrierName"]
    assert build_fcmaterials_message(data) is None


def test_missing_carrier_id_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["CarrierID"]
    assert build_fcmaterials_message(data) is None


def test_missing_timestamp_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["timestamp"]
    assert build_fcmaterials_message(data) is None


def test_not_a_dict_returns_none():
    assert build_fcmaterials_message(None) is None
    assert build_fcmaterials_message([]) is None


def test_empty_items_returns_none():
    assert build_fcmaterials_message(_fcmaterials([])) is None


def test_item_missing_id_is_dropped_but_others_survive():
    bad = _fc_item(name="$landmines_name;")
    del bad["id"]
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_item_with_non_int_price_is_dropped_but_others_survive():
    bad = _fc_item(name="$landmines_name;", Price="not a number")
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_item_with_bool_price_is_dropped():
    bad = _fc_item(name="$landmines_name;", Price=True)
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_all_items_invalid_returns_none():
    bad = _fc_item()
    del bad["id"]
    assert build_fcmaterials_message(_fcmaterials([bad])) is None


def test_maybe_publish_fcmaterials_queues_compliant_envelope():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({
        "event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000",
        "Horizons": False, "Odyssey": True,
    })

    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))

    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == _FCMATERIALS_SCHEMA_REF
    assert payload["header"]["uploaderID"] == "CMDR Test"
    assert payload["header"]["softwareName"] == "EDChronicle"
    assert payload["message"]["CarrierName"] == "TESTBED"
    assert payload["message"]["Items"][0]["Name"] == "$graphene_name;"
    assert payload["message"]["horizons"] is False
    assert payload["message"]["odyssey"] is True


def test_maybe_publish_fcmaterials_skips_when_no_commander_known():
    pub = EddnPublisher()
    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))
    assert pub._queue.empty()


def test_maybe_publish_fcmaterials_skips_invalid_data():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.maybe_publish_fcmaterials({"not": "valid fcmaterials"})
    assert pub._queue.empty()


def test_maybe_publish_fcmaterials_skips_beta_build():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0 beta 1", "build": "r300000"})

    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))

    assert pub._queue.empty()
