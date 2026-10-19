# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Second BGS tick source: spot the tick in the live EDDN feed.

Faction influence only changes at a tick, so when many systems' influence
changes within a short time, the tick has happened -- the same idea behind
tick.edcd.io, which listed no tick at all for 2026-10-18 while Ekono's
influence still moved. Fed from the EDDN listener thread (FSDJump/Location/
CarrierJump Factions); pure Python, no Qt or DB.

ponytail: the tick time is the earliest change seen in the triggering burst,
so it's accurate to within the first hour of propagation; good enough to
split Experiment Log windows (tick.edcd.io's time wins when it has one, as
ticks within 6 h are treated as the same tick).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

WINDOW = timedelta(minutes=60)      # changes this close together form a burst
MIN_SYSTEMS = 20                    # distinct systems changing in one burst
# EDDN is unauthenticated: the burst must come from several uploaders, so one
# sender can't fake a tick quickly (the relay re-hashes uploader IDs every 3
# min). ponytail: raises the bar, doesn't stop a patient faker -- tick.edcd.io's
# time replaces a detected tick when it has one (Repository.record_bgs_tick).
MIN_UPLOADERS = 5
MIN_GAP = timedelta(hours=16)       # ticks are daily; no second tick sooner
MAX_LAG = timedelta(minutes=30)     # ignore messages older than this (replayed journals)
FORGET = timedelta(hours=48)        # drop systems not seen for this long


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TickDetector:
    def __init__(self, last_tick: Optional[str] = None):
        self._levels: Dict[int, Tuple[datetime, tuple]] = {}
        self._changes: deque = deque()          # (time, system_address, uploader)
        self._last_tick = _parse(last_tick) if last_tick else None
        self._seen = 0

    def set_last_tick(self, tick: Optional[str]) -> None:
        """The newest known tick (from either source); keeps the 16 h gap honest."""
        t = _parse(tick) if tick else None
        if t and (self._last_tick is None or t > self._last_tick):
            self._last_tick = t

    def observe(self, system_address: Any, factions: List[dict], timestamp: str,
                now: Optional[datetime] = None, uploader: Optional[str] = None) -> Optional[str]:
        """Feed one message's Factions; returns the tick time (…Z) when this
        message completes a burst, else None."""
        ts = _parse(timestamp)
        now = now or datetime.now(timezone.utc)
        if ts is None or not isinstance(system_address, int) or not isinstance(factions, list):
            return None
        if now - ts > MAX_LAG or ts - now > timedelta(minutes=5):
            return None
        levels = tuple(sorted((f["Name"], round(f["Influence"], 4)) for f in factions
                              if isinstance(f, dict) and isinstance(f.get("Name"), str)
                              and isinstance(f.get("Influence"), (int, float)) and f["Influence"] > 0))
        if not levels:
            return None
        self._seen += 1
        if self._seen % 5000 == 0:
            self._levels = {a: v for a, v in self._levels.items() if now - v[0] < FORGET}
        prev = self._levels.get(system_address)
        if prev is not None and ts <= prev[0]:
            return None
        self._levels[system_address] = (ts, levels)
        if prev is None or prev[1] == levels:
            return None
        self._changes.append((ts, system_address, uploader))
        while self._changes and ts - self._changes[0][0] > WINDOW:
            self._changes.popleft()
        if (len({c[1] for c in self._changes}) < MIN_SYSTEMS
                or len({c[2] for c in self._changes if c[2]}) < MIN_UPLOADERS):
            return None
        tick = min(c[0] for c in self._changes)
        if self._last_tick is not None and tick - self._last_tick < MIN_GAP:
            return None
        self._last_tick = tick
        self._changes.clear()
        return _iso(tick)
