"""outfitting/2 and shipyard/2 from Outfitting.json / Shipyard.json, per the
EDDN schema READMEs: names only, Cmdr-dependent modules removed."""
from edc.core.eddn_publisher import EddnPublisher, build_outfitting_message, build_shipyard_message

HEAD = {"timestamp": "2026-10-11T19:10:42Z", "MarketID": 3225590528, "StationName": "Lundmark Terminal",
        "StarSystem": "Ekono", "Horizons": True}


def test_outfitting_keeps_station_modules_only():
    data = {**HEAD, "event": "Outfitting", "Items": [
        {"id": 1, "Name": "hpt_railgun_fixed_small", "BuyPrice": 50310},
        {"id": 2, "Name": "int_engine_size3_class5", "BuyPrice": 1},
        {"id": 3, "Name": "anaconda_armour_grade1", "BuyPrice": 1},
        {"id": 4, "Name": "int_planetapproachsuite", "BuyPrice": 1},       # README: always removed
        {"id": 5, "Name": "bobble_pilot", "BuyPrice": 1},                  # not a station module
        {"id": 6, "Name": "hpt_railgun_fixed_small", "BuyPrice": 50310}]}  # duplicate
    assert build_outfitting_message(data) == {
        "systemName": "Ekono", "stationName": "Lundmark Terminal", "marketId": 3225590528,
        "timestamp": "2026-10-11T19:10:42Z",
        "modules": ["hpt_railgun_fixed_small", "int_engine_size3_class5", "anaconda_armour_grade1"]}


def test_shipyard_ship_names_and_cobra_flag():
    data = {**HEAD, "event": "Shipyard", "AllowCobraMkIV": False, "PriceList": [
        {"id": 0, "ShipType": "panthermkii", "ShipType_Localised": "Panther Clipper Mk II", "ShipPrice": 1}]}
    msg = build_shipyard_message(data)
    assert msg["ships"] == ["panthermkii"] and msg["allowCobraMkIV"] is False
    assert build_shipyard_message({**HEAD, "PriceList": []}) is None


def test_published_with_flags_on_own_schema():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR T", "Horizons": True, "Odyssey": True})
    pub.maybe_publish_station_list("shipyard", {**HEAD, "PriceList": [{"ShipType": "sidewinder"}]})
    p = pub._queue.get_nowait()
    assert p["$schemaRef"] == "https://eddn.edcd.io/schemas/shipyard/2" and p["message"]["odyssey"] is True
