"""Pure trade-loop-finding logic for the Trade Route Loop Planner — no Qt,
no DB, just data in/data out so it's independently testable. See
docs/superpowers/specs/2026-08-09-trade-route-loop-planner-design.md.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# A loop older than this (its stalest leg) is ranked below every fresher
# loop regardless of profit, rather than excluded outright — a stale route
# is still better than no route at all in a sparse area, but shouldn't
# outrank a real, trustworthy one. Matches the UI's own red-flag threshold.
STALE_THRESHOLD_HOURS = 24 * 7


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    """last_updated isn't one consistent format: EDDN messages' own
    timestamps are typically "...SS.mmmZ" (milliseconds + Z), while our
    own generated fallback timestamps are Python's isoformat() with a
    "+00:00" offset instead of "Z" — datetime.fromisoformat handles both
    once "Z" is normalized to an explicit offset."""
    if not isinstance(ts, str):
        return None
    try:
        normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalized)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_commodity_name(name: str) -> str:
    """Duplicated from edc/ui/panels/market_panel.py's identical function
    rather than imported -- this module is deliberately Qt/DB-free (see
    module docstring), and importing from a UI-layer module would run
    the dependency the wrong direction for two lines of regex."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def find_point_to_point_trades(
    origin_items: List[Dict[str, Any]],
    destination_stations: Dict[int, dict],
    cargo_capacity: int,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    For every commodity buyable at the origin (state.current_market_items
    shape), finds the best-selling destination station for it -- if the
    destination system has more than one station selling it -- and
    computes a cargo-capacity-capped total profit, same formula as
    _best_leg() uses for the Loop Planner. Commodities with no
    positive-margin destination are excluded entirely, not returned as
    zero/negative rows. Returns up to max_results, sorted by total
    profit descending.
    """
    results: List[Dict[str, Any]] = []

    for item in origin_items:
        display_name = item.get("name")
        buy_price = item.get("buy_price")
        stock = item.get("stock")
        if not isinstance(display_name, str) or not display_name:
            continue
        if not isinstance(buy_price, int) or buy_price <= 0:
            continue
        if not isinstance(stock, int) or stock <= 0:
            continue

        symbol = item.get("symbol") or _normalize_commodity_name(display_name)
        symbol_lower = symbol.lower()
        best: Optional[Dict[str, Any]] = None

        for station in destination_stations.values():
            sell_info = None
            for stored_commodity, info in station["sells"].items():
                if stored_commodity.lower() == symbol_lower:
                    sell_info = info
                    break
            if sell_info is None:
                continue
            sell_price, demand, last_updated = sell_info
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
            if best is None or total > best["total_profit"]:
                dt = _parse_ts(last_updated)
                age_hours = (
                    (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
                    if dt else None
                )
                best = {
                    "commodity": display_name,
                    "sell_station_name": station["station_name"],
                    "sell_system_name": station["system_name"],
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit_per_unit": profit_per_unit,
                    "quantity": qty,
                    "total_profit": total,
                    "data_age_hours": age_hours,
                }

        if best is not None:
            results.append(best)

    results.sort(
        key=lambda r: (
            r["data_age_hours"] is None or r["data_age_hours"] < STALE_THRESHOLD_HOURS,
            r["total_profit"],
        ),
        reverse=True,
    )
    return results[:max_results]


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
    descending, capped at max_results. "Station A" is always whichever
    end of the loop is closer to the reference point passed into
    get_market_snapshot_in_radius (i.e. wherever you actually are) —
    each station dict's own "distance_ly" field, carried through as
    "dist_from_you" on the loop — so results always read as "fly here
    first," not an arbitrary pairing order.
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

            # "Station A" always means "whichever end of the loop is
            # closer to you right now" — the pairing above is symmetric
            # (A->B->A and B->A->B are the same loop), so without this the
            # dict-iteration order decided which one got called "A", with
            # no relation to which one you'd actually want to fly to first.
            # Uses fresh names rather than reassigning a/b/leg_ab/leg_ba in
            # place — those are the outer/inner loop-carried variables, and
            # mutating them here corrupted every later inner iteration once
            # one swap fired (confirmed live: produced dozens of bogus
            # duplicate-looking pairs, and separately caused real valid
            # pairs to vanish since the wrong "a" station got compared
            # against the next id_b instead of the true one).
            if b["distance_ly"] < a["distance_ly"]:
                out_a, out_b = b, a
                out_leg_ab, out_leg_ba = leg_ba, leg_ab
            else:
                out_a, out_b = a, b
                out_leg_ab, out_leg_ba = leg_ab, leg_ba

            ages = [
                h for h in (out_leg_ab["data_age_hours"], out_leg_ba["data_age_hours"])
                if h is not None
            ]
            data_age_hours = max(ages) if ages else None

            loops.append({
                "station_a": out_a["station_name"], "system_a": out_a["system_name"], "pad_a": out_a["pad_size"],
                "station_b": out_b["station_name"], "system_b": out_b["system_name"], "pad_b": out_b["pad_size"],
                "distance_ly": distance_ly,
                "dist_from_you": out_a["distance_ly"],
                "leg_a_to_b": out_leg_ab,
                "leg_b_to_a": out_leg_ba,
                "total_profit": out_leg_ab["profit"] + out_leg_ba["profit"],
                "data_age_hours": data_age_hours,
            })

    # Fresh loops always rank ahead of stale ones regardless of profit —
    # a bigger number backed by day-old demand data isn't actually the
    # better route (confirmed live: a top-ranked route's real profit came
    # in well under what was shown, traced to unflagged stale data).
    # Within each freshness tier, still ranked by profit.
    loops.sort(
        key=lambda r: (
            r["data_age_hours"] is None or r["data_age_hours"] < STALE_THRESHOLD_HOURS,
            r["total_profit"],
        ),
        reverse=True,
    )
    return loops[:max_results]


def _best_leg(buy_station: dict, sell_station: dict, cargo_capacity: int) -> Optional[dict]:
    """Best single commodity to buy at `buy_station` and sell at
    `sell_station`, by total profit for this leg (not just profit/unit —
    a cheaper-margin commodity with far more available stock/demand can
    beat a thin-margin one that's capped to a handful of units)."""
    best: Optional[dict] = None
    for commodity, (buy_price, stock, buy_updated) in buy_station["buys"].items():
        sell_info = sell_station["sells"].get(commodity)
        if sell_info is None:
            continue
        sell_price, demand, sell_updated = sell_info
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

        # Whichever side's data is older is what a player would actually
        # run into first — the buy price/stock could be fresh while the
        # sell side's demand quietly drifted for days, or vice versa.
        ages = [dt for dt in (_parse_ts(buy_updated), _parse_ts(sell_updated)) if dt is not None]
        data_age_hours = (
            (datetime.now(timezone.utc) - min(ages)).total_seconds() / 3600.0
            if ages else None
        )

        total = profit_per_unit * qty
        if best is None or total > best["profit"]:
            best = {
                "commodity": commodity,
                "profit_per_unit": profit_per_unit,
                "quantity": qty,
                "profit": total,
                "data_age_hours": data_age_hours,
            }
    return best
