"""Regression test for find_trade_loops' station-pairing swap logic.

Reproduces a real bug found live: the "make station_a always the closer
one" swap mutated the outer loop's `a` variable in place without
resetting it for the next inner-loop iteration, so once one swap fired,
`a` stayed corrupted (stuck pointing at the wrong station) for every
remaining pairing in that outer pass -- producing bogus/duplicate-looking
loop entries that don't correspond to any real station pair.
"""
from datetime import datetime, timezone

from edc.core.trade_routes import find_trade_loops

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


if __name__ == "__main__":
    test_swap_does_not_corrupt_later_pairings()
    print("OK")
