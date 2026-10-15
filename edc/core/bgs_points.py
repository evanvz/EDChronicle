# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""BGS effort as SINC "bucket points" and the likely daily influence ceiling.

Points (Complete BGS Guide 2024 p65, from Cmdr Taipandot; community-measured):
each bucket is 'coef x log2(value / base)', so every doubling adds the same
coef -- diminishing returns, and a little in an empty bucket beats a lot more
in a full one. The points are relative effort, not influence percent.

Ceiling: in 121 clean EUW day-pairs (fresh readings on consecutive days, no
war/election; 2026-07-30..10-12) a faction's daily gain as a share of its
headroom (100% - influence) was typically at most 6-8% (p75 5.0%, p90 8.3%,
record 13.2%), matching a forum-reported ~6% "real" cap per tick that shrinks
after renormalising to 100%. A guide, not a hard wall.

Population: SINC's daily amounts per system grow with population (p69: small
< 1m, medium 1-25m, large > 25m). Each bucket's base is scaled by the same
ratio as SINC's amount for that size vs a small system, so medium/large
systems need proportionally more for the same points. Our own scaling of
SINC's table, not a measured rule; unknown population = small (unscaled).
"""
from __future__ import annotations

import math
from typing import Optional

# bucket: (coef, base) -- points = coef x log2(value / base), 0 at or below base
_BUCKETS = {
    "missions": (0.5, 1),           # INF
    "bounties": (1.33, 450_000),    # credits redeemed
    "trade": (0.5, 100_000),        # trade profit
    "exploration": (0.5, 1_000_000),  # cartographic data sold
}
CEILING_SHARE = (0.06, 0.08)        # of headroom, see module docstring
_TARGET_KEYS = {"missions": "tier_score", "bounties": "bounties", "trade": "trade_profit",
                "exploration": "exploration"}


def _bases(population) -> dict:
    """Bucket bases for a system of this population (see module docstring)."""
    from edc.core.bgs_tasks import population_targets   # bgs_tasks imports this module
    small, size = population_targets(1), population_targets(population)
    return {name: base * (size[_TARGET_KEYS[name]] / small[_TARGET_KEYS[name]] if size else 1)
            for name, (_coef, base) in _BUCKETS.items()}


def _human(n: float) -> str:
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.3g}{suffix}"
    return f"{n:.0f}"


def bucket_points(inf: int, bounties: int, trade_profit: int, exploration: int, population=None) -> dict:
    values = {"missions": inf, "bounties": bounties, "trade": trade_profit, "exploration": exploration}
    bases = _bases(population)
    out = {}
    for name, (coef, _base) in _BUCKETS.items():
        v, base = values[name] or 0, bases[name]
        out[name] = coef * math.log2(v / base) if v > base else 0
    return out


def total_points(points: dict) -> float:
    return sum(points.values())


def bucket_hints(inf: int, bounties: int, trade_profit: int, exploration: int, population=None) -> dict:
    """{"empty": buckets with no points yet, "next": per bucket, what the next
    equal step (+coef points) costs: the first 2 x base, or another doubling}."""
    values = {"missions": inf, "bounties": bounties, "trade": trade_profit, "exploration": exploration}
    bases = _bases(population)
    empty, nxt = [], {}
    for name, (coef, _base) in _BUCKETS.items():
        v, base = values[name] or 0, bases[name]
        unit = " INF" if name == "missions" else ""
        if v <= base:
            empty.append(name)
            nxt[name] = f"first {_human(2 * base)}{unit} → +{coef:g}"
        else:
            nxt[name] = f"another {_human(v)}{unit} → +{coef:g}"
    return {"empty": empty, "next": nxt}


def ceiling(influence: Optional[float]) -> Optional[tuple]:
    """Likely best daily gain, in influence points, for a faction at this share."""
    if not isinstance(influence, (int, float)):
        return None
    headroom = (1 - influence) * 100
    return CEILING_SHARE[0] * headroom, CEILING_SHARE[1] * headroom
