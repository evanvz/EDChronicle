from edc.core.trade_routes import plan_supply_stops, docked_supply


def _st(name, dist, pad, **buys):
    return {"station_name": name, "system_name": name + " Sys", "pad_size": pad, "distance_ly": dist,
            "buys": {k: (100, stock, "2026-11-14T10:00:00Z") for k, stock in buys.items()}}


NEEDS = {"steel": 836, "robotics": 118, "mutomimager": 90}


def test_fewest_stops_first_then_nearest():
    stations = {
        1: _st("Near One", 10, "L", steel=5000),
        2: _st("Far Two", 40, "L", Steel=5000, robotics=500),     # mixed-case spelling in the cache
        3: _st("Mid Two", 30, "L", steel=5000, robotics=500),
        4: _st("Imager", 45, "L", mutomimager=200),
    }
    stops, unmet = plan_supply_stops(NEEDS, stations, "L")
    assert [s["station_name"] for s in stops] == ["Mid Two", "Imager"]
    assert stops[0]["items"] == [("robotics", 118, 500), ("steel", 836, 5000)]
    assert unmet == {}


def test_pad_filter_short_stock_and_unmet():
    stations = {
        1: _st("Outpost", 5, "M", steel=5000, robotics=500, mutomimager=500),
        2: _st("Unknown Pad", 6, "?", steel=5000),
        3: _st("Short", 20, "L", steel=300),
        4: _st("Rest", 25, "L", steel=5000),
    }
    stops, unmet = plan_supply_stops(NEEDS, stations, "L")
    # A station that covers the full amount beats a nearer one that is short.
    assert [(s["station_name"], s["items"]) for s in stops] == [("Rest", [("steel", 836, 5000)])]
    assert unmet == {"robotics": 118, "mutomimager": 90}
    assert plan_supply_stops(NEEDS, stations, None)[0][0]["station_name"] == "Outpost"


def test_nearer_ring_wins_when_it_covers_everything():
    stations = {
        1: _st("A", 20, "L", steel=900),
        2: _st("B", 45, "L", robotics=200, mutomimager=100),
        3: _st("All", 120, "L", steel=5000, robotics=500, mutomimager=500),
    }
    stops, unmet = plan_supply_stops(NEEDS, stations, "L")
    assert [s["station_name"] for s in stops] == ["B", "A"] and unmet == {}


def test_docked_supply_reads_the_live_market():
    items = [{"name": "Steel", "symbol": "steel", "buy_price": 4000, "stock": 500},
             {"name": "Robotics", "symbol": "robotics", "buy_price": 0, "stock": 0},
             {"name": "Gold", "symbol": "gold", "buy_price": 9000, "stock": 50}]
    assert docked_supply(NEEDS, items) == [("steel", 500, 500)]
