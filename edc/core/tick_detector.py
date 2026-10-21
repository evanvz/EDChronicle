# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Second BGS tick source: spot the tick in the live EDDN feed.

Faction influence only changes at a tick, so when many systems' influence
changes within a short time, the tick has happened -- the same idea behind
tick.edcd.io, which listed no tick at all for 2026-10-18 while Ekono's
influence still moved. Fed from the EDDN listener thread (FSDJump/Location/
CarrierJump Factions); pure Python, no Qt or DB.

Lessons from EDCAS's server-side detector (arne-fuchs/edcas-client,
crates/edcas-server/src/tick.rs), adopted 2026-10-21 after our first version
fired at 10-20 11:33 and 10-21 03:49 UTC, 16 h apart and unconfirmed by any
monitored system: for hours after a tick some uploaders keep sending the old
values, so comparing message-to-message flip-flops. Now:
- each reading is compared with that system's settled value from 2+ h earlier;
- only a move of more than 0.5 points in some faction counts;
- the 3 h before the burst must have been quiet, and ticks are 20+ h apart.

ponytail: the tick time is the earliest change in the triggering burst, so
it's accurate to within the first hour of propagation; tick.edcd.io's time
replaces it when it has one (Repository.record_bgs_tick).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

WINDOW = timedelta(minutes=60)      # changes this close together form a burst
MIN_SYSTEMS = 20                    # distinct systems changing in one burst
# EDDN is unauthenticated: the burst must come from several uploaders, so one
# sender can't fake a tick quickly (the relay re-hashes uploader IDs every 3 min).
MIN_UPLOADERS = 5
MIN_GAP = timedelta(hours=20)       # EDCAS: ticks closer than 20 h are false positives
REFERENCE_AGE = timedelta(hours=2)  # compare with the system's value at least this old
CHANGE = 0.005                      # 0.5 points of influence (EDCAS)
QUIET = timedelta(hours=3)          # the lull before a tick (EDCAS)
QUIET_MAX = 3                       # changed systems allowed in that lull
MAX_LAG = timedelta(minutes=30)     # ignore messages older than this (replayed journals)
FORGET = timedelta(hours=48)        # drop systems not seen for this long


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _moved(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return any(abs(a[f] - b[f]) > CHANGE for f in set(a) & set(b))


class TickDetector:
    def __init__(self, last_tick: Optional[str] = None):
        self._history: Dict[int, deque] = {}    # system -> [(time, {faction: influence})], oldest first
        self._changes: deque = deque()          # (time, system_address, uploader), last QUIET + WINDOW
        self._last_tick = _parse(last_tick) if last_tick else None
        self._seen = 0

    def set_last_tick(self, tick: Optional[str]) -> None:
        """The newest known tick (from either source); keeps the 20 h gap honest."""
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
        levels = {f["Name"]: f["Influence"] for f in factions
                  if isinstance(f, dict) and isinstance(f.get("Name"), str)
                  and isinstance(f.get("Influence"), (int, float)) and f["Influence"] > 0}
        if not levels:
            return None
        self._seen += 1
        if self._seen % 5000 == 0:
            self._history = {a: h for a, h in self._history.items() if h and now - h[-1][0] < FORGET}
        hist = self._history.setdefault(system_address, deque())
        # the settled reference: the newest reading at least REFERENCE_AGE old
        ref = next((lv for t, lv in reversed(hist) if ts - t >= REFERENCE_AGE), None)
        hist.append((ts, levels))
        while len(hist) > 2 and ts - hist[1][0] >= REFERENCE_AGE:
            hist.popleft()          # keep one reading older than the reference age, drop the rest
        if ref is None or not _moved(ref, levels):
            return None
        if any(c[1] == system_address for c in self._changes if ts - c[0] <= WINDOW):
            return None             # this system already counted in the current hour
        self._changes.append((ts, system_address, uploader))
        while self._changes and ts - self._changes[0][0] > QUIET + WINDOW:
            self._changes.popleft()
        burst = [c for c in self._changes if ts - c[0] <= WINDOW]
        if len({c[1] for c in burst}) < MIN_SYSTEMS or len({c[2] for c in burst if c[2]}) < MIN_UPLOADERS:
            return None
        tick = min(c[0] for c in burst)
        lull = [c for c in self._changes if tick - QUIET <= c[0] < tick]
        if len({c[1] for c in lull}) > QUIET_MAX and len({c[2] for c in lull if c[2]}) >= MIN_UPLOADERS:
            return None             # not a lull -> activity smear after an earlier tick, not a new one
            # (needs several uploaders too, so one sender can't suppress a real tick)
        if self._last_tick is not None and tick - self._last_tick < MIN_GAP:
            return None
        self._last_tick = tick
        self._changes.clear()
        return _iso(tick)
