"""Pure trade-loop-finding logic for the Trade Route Loop Planner — no Qt,
no DB, just data in/data out so it's independently testable. See
docs/superpowers/specs/2026-08-09-trade-route-loop-planner-design.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def find_trade_loops(
    stations: Dict[int, dict],
    cargo_capacity: int,
    max_results: int = 50,
) -> List[dict]:
    """
    Finds every A<->B pair (market_id keys of `stations`, as returned by
    Repository.get_market_snapshot_in_radius) where a real A->B->A round
    trip is profitable in both directions — not a one-way flip.

    For each ordered pair, "buy" at a station means its buy_price/stock
    (station sells to the player); "sell" means its sell_price/demand
    (station buys from the player) — matching market_prices' own column
    naming, which is from the STATION's point of view.

    Returns loops sorted by total round-trip profit (both legs, each
    capped by cargo_capacity and that leg's own stock/demand — you can't
    buy more than a station has in stock or sell more than it demands),
    descending, capped at max_results.
    """
    market_ids = list(stations.keys())
    loops: List[dict] = []

    for i, id_a in enumerate(market_ids):
        a = stations[id_a]
        for id_b in market_ids[i + 1:]:
            b = stations[id_b]

            leg_ab = _best_leg(a, b, cargo_capacity)  # buy at A, sell at B
            if leg_ab is None:
                continue
            leg_ba = _best_leg(b, a, cargo_capacity)  # buy at B, sell at A
            if leg_ba is None:
                continue

            distance_ly = (
                (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2
            ) ** 0.5

            loops.append({
                "station_a": a["station_name"], "system_a": a["system_name"], "pad_a": a["pad_size"],
                "station_b": b["station_name"], "system_b": b["system_name"], "pad_b": b["pad_size"],
                "distance_ly": distance_ly,
                "leg_a_to_b": leg_ab,
                "leg_b_to_a": leg_ba,
                "total_profit": leg_ab["profit"] + leg_ba["profit"],
            })

    loops.sort(key=lambda r: r["total_profit"], reverse=True)
    return loops[:max_results]


def _best_leg(buy_station: dict, sell_station: dict, cargo_capacity: int) -> Optional[dict]:
    """Best single commodity to buy at `buy_station` and sell at
    `sell_station`, by total profit for this leg (not just profit/unit —
    a cheaper-margin commodity with far more available stock/demand can
    beat a thin-margin one that's capped to a handful of units)."""
    best: Optional[dict] = None
    for commodity, (buy_price, stock) in buy_station["buys"].items():
        sell_info = sell_station["sells"].get(commodity)
        if sell_info is None:
            continue
        sell_price, demand = sell_info
        profit_per_unit = sell_price - buy_price
        if profit_per_unit <= 0:
            continue

        qty = cargo_capacity
        if isinstance(stock, int) and stock > 0:
            qty = min(qty, stock)
        if isinstance(demand, int) and demand > 0:
            qty = min(qty, demand)
        if qty <= 0:
            continue

        total = profit_per_unit * qty
        if best is None or total > best["profit"]:
            best = {
                "commodity": commodity,
                "profit_per_unit": profit_per_unit,
                "quantity": qty,
                "profit": total,
            }
    return best
