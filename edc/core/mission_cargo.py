# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Mission Cargo: what the active cargo missions still need and where to buy it.

Missions come from state.active_missions (MissionAccepted carries Commodity,
Count, DestinationStation, Expiry; CargoDepot updates ItemsDelivered -- see
edc.core.mission_events). Missions for the same commodity and drop-off station
are combined. Collect/source and mining missions get buy suggestions; delivery
missions hand you the cargo and salvage can't be bought, so those only show
progress.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edc.core.trade_routes import commodity_key

_PAD_RANK = {"S": 1, "M": 2, "L": 3}


def _buyable(mission_name: str) -> bool:
    n = (mission_name or "").lower()
    return not (n.startswith("mission_delivery") or "salvage" in n)


def commodity_aliases(raw: str, localised: Optional[str]) -> List[str]:
    """Every spelling the market cache may hold for a mission commodity
    ('$AtmosphericExtractors_Name;'): EDDN's lowercase symbol, the mixed-case
    symbol, both $..._Name; forms and the in-game name. Exact names keep the
    market search on its index (a case-insensitive match would scan ~14M rows)."""
    sym = (raw or "").strip()
    if sym.startswith("$"):
        sym = sym[1:]
    if sym.lower().endswith("_name;"):
        sym = sym[:-len("_name;")]
    names = {sym.lower(), sym, f"${sym}_Name;", f"${sym.lower()}_name;", raw or ""}
    if localised:
        names.add(localised)
    return sorted(n for n in names if n)


def cargo_needs(active_missions: Dict[int, Dict[str, Any]], cargo_inventory: List[Dict[str, Any]],
                now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One row per (commodity, drop-off station): missions, total, delivered,
    needed (total - delivered), held (in the hold now), to_buy (needed - held,
    at least 0), earliest expiry, buyable, plus raw/aliases for the market search.

    Expired missions are skipped: one that runs out while the game is closed
    never gets a MissionFailed, so it stays in active_missions. On-foot missions
    (Mission_OnFoot_*: schematics, samples) carry items, not market commodities."""
    now_iso = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    held: Dict[str, int] = {}
    for c in cargo_inventory or []:
        if isinstance(c, dict) and isinstance(c.get("Count"), int):
            key = commodity_key(c.get("Name") or "")
            held[key] = held.get(key, 0) + c["Count"]

    rows: Dict[tuple, Dict[str, Any]] = {}
    for rec in (active_missions or {}).values():
        raw, count = rec.get("commodity"), rec.get("count")
        if not raw or not isinstance(count, int) or count <= 0:
            continue
        if "onfoot" in (rec.get("name") or "").lower() or (rec.get("expiry") or "9999") < now_iso:
            continue
        key = commodity_key(raw)
        group = rows.setdefault((key, rec.get("destination_station") or ""), {
            "key": key, "raw": raw, "aliases": commodity_aliases(raw, rec.get("commodity_localised")),
            "commodity": rec.get("commodity_localised") or raw,
            "system": rec.get("destination_system") or "", "station": rec.get("destination_station") or "",
            "missions": 0, "total": 0, "delivered": 0, "expiry": None, "buyable": False,
        })
        group["missions"] += 1
        group["total"] += count
        group["delivered"] += min(rec.get("delivered") or 0, count)
        expiry = rec.get("expiry")
        if expiry and (group["expiry"] is None or expiry < group["expiry"]):
            group["expiry"] = expiry
        group["buyable"] = group["buyable"] or _buyable(rec.get("name"))

    out = []
    for g in rows.values():
        g["needed"] = g["total"] - g["delivered"]
        g["held"] = held.get(g["key"], 0)
        g["to_buy"] = max(0, g["needed"] - g["held"])
        out.append(g)
    return sorted(out, key=lambda g: (g["expiry"] or "9999", g["commodity"]))


def pick_sources(rows: List[Dict[str, Any]], to_buy: int, required_pad: Optional[str]) -> Dict[str, Any]:
    """From search_market_buy_prices() rows: the nearest and the cheapest source
    that fits the pad, those with stock for the whole amount ranking first, and
    every fitting source sorted by distance."""
    need_rank = _PAD_RANK.get(required_pad or "", 0)
    fits = [r for r in rows if _PAD_RANK.get(r.get("pad_size") or "", 0) >= need_rank]
    fits.sort(key=lambda r: r.get("distance_ly") or 0.0)

    def short(r):
        return (r.get("stock") or 0) < to_buy
    return {
        "nearest": min(fits, key=lambda r: (short(r), r.get("distance_ly") or 0.0), default=None),
        "cheapest": min(fits, key=lambda r: (short(r), r.get("buy_price") or 0, r.get("distance_ly") or 0.0), default=None),
        "all": fits,
    }
