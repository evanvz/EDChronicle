"""Regression test for find_trade_loops' station-pairing swap logic.

Reproduces a real bug found live: the "make station_a always the closer
one" swap mutated the outer loop's `a` variable in place without
resetting it for the next inner-loop iteration, so once one swap fired,
`a` stayed corrupted (stuck pointing at the wrong station) for every
remaining pairing in that outer pass -- producing bogus/duplicate-looking
loop entries that don't correspond to any real station pair.
"""
from datetime import datetime, timezone

from edc.core.trade_routes import find_trade_loops, find_point_to_point_trades

_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _station(name, dist, buys=None, sells=None):
    return {
        "station_name": name, "system_name": name + "_sys", "pad_size": 3,
        "x": dist, "y": 0, "z": 0, "distance_ly": dist,
        "buys": buys or {}, "sells": sells or {},
    }


def test_swap_does_not_corrupt_later_pairings():
    # Distances: A=10 (farthest from you), B=1 (closest), C=5 (middle).
    # Outer loop fixes id_a=A; inner loop visits B then C.
    #   (A, B): B is closer -> swap fires, station_a becomes B.
    #   (A, C): correct behavior re-derives a=A(10) vs b=C(5) -> C closer,
    #     station_a should be C. The bug instead leaves `a` stuck as B(1)
    #     from the previous iteration, comparing C(5) against B(1) instead
    #     of against the true A(10) -- no swap fires, and the loop wrongly
    #     reports "B <-> C", a pair that shares no commodities at all.
    stations = {
        1: _station("A", 10, buys={"w": (10, 1000, _NOW)}, sells={"g": (200, 1000, _NOW)}),
        2: _station("B", 1, buys={"g": (20, 1000, _NOW)}, sells={"w": (50, 1000, _NOW)}),
        3: _station("C", 5, buys={"g": (30, 1000, _NOW)}, sells={"w": (60, 1000, _NOW)}),
    }

    loops = find_trade_loops(stations, cargo_capacity=100, max_results=50)

    pairs = {frozenset((l["station_a"], l["station_b"])) for l in loops}
    assert frozenset(("B", "C")) not in pairs, (
        f"corrupted pairing 'B <-> C' leaked into results: {loops}"
    )
    assert pairs == {frozenset(("A", "B")), frozenset(("A", "C"))}

    for loop in loops:
        if frozenset((loop["station_a"], loop["station_b"])) == frozenset(("A", "C")):
            assert loop["station_a"] == "C"  # closer of the two (5 < 10)
            assert loop["station_b"] == "A"


def _origin_item(name, buy_price, stock):
    return {"name": name, "category": "", "buy_price": buy_price, "sell_price": 0, "demand": 0, "stock": stock}


def _dest_station(name, system, sells=None):
    return {
        "station_name": name, "system_name": system, "pad_size": 3,
        "controlling_faction": None, "sells": sells or {}, "buys": {},
    }


def test_point_to_point_finds_profitable_commodity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=500)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 200, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    r = results[0]
    assert r["commodity"] == "Platinum"
    assert r["sell_station_name"] == "Jameson Memorial"
    assert r["buy_price"] == 1000
    assert r["sell_price"] == 1500
    assert r["profit_per_unit"] == 500


def test_point_to_point_excludes_negative_margin():
    origin_items = [_origin_item("Platinum", buy_price=2000, stock=500)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 200, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert results == []


def test_point_to_point_caps_quantity_at_cargo_capacity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=5000)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 5000, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=64)
    assert results[0]["quantity"] == 64
    assert results[0]["total_profit"] == 500 * 64


def test_point_to_point_caps_quantity_at_stock_and_demand():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=10)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 3, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=500)
    assert results[0]["quantity"] == 3  # demand is the tightest cap


def test_point_to_point_picks_best_station_for_same_commodity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=500)]
    destination_stations = {
        1: _dest_station("Low Price Station", "System A", sells={"platinum": (1200, 500, _NOW)}),
        2: _dest_station("High Price Station", "System B", sells={"platinum": (1600, 500, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    assert results[0]["sell_station_name"] == "High Price Station"
    assert results[0]["profit_per_unit"] == 600


def test_point_to_point_truncates_to_max_results():
    origin_items = [
        _origin_item("Platinum", buy_price=1000, stock=100),
        _origin_item("Gold", buy_price=500, stock=100),
        _origin_item("Silver", buy_price=200, stock=100),
    ]
    destination_stations = {
        1: _dest_station("Station", "System", sells={
            "platinum": (1500, 100, _NOW),
            "gold": (900, 100, _NOW),
            "silver": (400, 100, _NOW),
        }),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100, max_results=2)
    assert len(results) == 2
    # sorted by total profit descending
    assert results[0]["total_profit"] >= results[1]["total_profit"]


def test_point_to_point_normalizes_commodity_names_for_matching():
    origin_items = [_origin_item("Low Temperature Diamonds", buy_price=1000, stock=100)]
    destination_stations = {
        1: _dest_station("Station", "System", sells={"lowtemperaturediamonds": (1500, 100, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    assert results[0]["commodity"] == "Low Temperature Diamonds"


def test_point_to_point_ignores_items_with_no_buy_price_or_stock():
    origin_items = [
        _origin_item("Platinum", buy_price=0, stock=500),      # not purchasable here
        _origin_item("Gold", buy_price=500, stock=0),          # nothing in stock
    ]
    destination_stations = {
        1: _dest_station("Station", "System", sells={
            "platinum": (1500, 100, _NOW), "gold": (900, 100, _NOW),
        }),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert results == []


if __name__ == "__main__":
    test_swap_does_not_corrupt_later_pairings()
    print("OK")
