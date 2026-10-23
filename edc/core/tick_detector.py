# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Second BGS tick source: spot the tick in the live EDDN feed.

Faction influence only changes at a tick, so when far more systems than
usual change influence within an hour, the tick has happened -- the idea
behind tick.edcd.io, which has listed no tick since 2026-10-17. Fed from the
EDDN listener thread (FSDJump/Location/CarrierJump Factions); no Qt or DB.

Rules (redesigned 2026-10-23 after the fixed thresholds misfired both ways):
- each reading is compared with that system's value from 2+ h earlier (stale
  uploads flip-flop message to message, EDCAS tick.rs); a move of more than
  0.5 points in any faction is a change;
- some systems change every hour anyway (late updates, stale uploads) -- 20 an
  hour with 4,600 systems watched, 75-200 overnight with more -- so the test
  is relative: the share of compared systems that changed in the last hour
  must be RATIO times the usual share (median of the previous hours);
- at least MIN_UPLOADERS uploaders (EDDN is unauthenticated) and MIN_CHANGED
  systems, and ticks are 12+ h apart (10-20 11:33 and 10-21 03:49 were 16 h).
The per-system readings and hourly shares are saved now and then and reloaded
at start, so a restart doesn't blind the detector for hours.

ponytail: RATIO is a first guess; snapshot() logs the shares so it can be set
from a real tick's burst.
"""
from __future__ import annotations

import gzip
import json
import logging
import statistics
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

WINDOW = timedelta(minutes=60)      # the hour whose share of changed systems is tested
REFERENCE_AGE = timedelta(hours=2)  # compare with the system's value at least this old
CHANGE = 0.005                      # 0.5 points of influence (EDCAS)
RATIO = 3.0                         # last hour's share of changed systems vs the usual share
BASELINE_HOURS = 6                  # the usual share: median of up to this many earlier hours
MIN_BASELINE_HOURS = 3              # ...and needs at least this many with enough systems
MIN_HOUR_SYSTEMS = 50               # an hour with fewer compared systems says too little
MIN_CHANGED = 10                    # changed systems in the hour
# EDDN is unauthenticated: the burst must come from several uploaders, so one
# sender can't fake a tick quickly (the relay re-hashes uploader IDs every 3 min).
MIN_UPLOADERS = 5
MIN_GAP = timedelta(hours=12)       # real ticks came 16-19 h apart (2026-10-20/21)
MAX_LAG = timedelta(minutes=30)     # ignore messages older than this (replayed journals)
FORGET = timedelta(hours=48)        # drop systems not seen for this long
SAVE_EVERY = timedelta(minutes=15)


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _moved(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return any(abs(a[f] - b[f]) > CHANGE for f in set(a) & set(b))


class TickDetector:
    def __init__(self, last_tick: Optional[str] = None, state_path: Optional[Path] = None):
        self._history: Dict[int, deque] = {}    # system -> [(time, {faction: influence})], oldest first
        self._recent: deque = deque()           # (time, system, changed, uploader) compared readings, last WINDOW
        self._hours: Dict[datetime, Tuple[set, set]] = {}   # hour -> (compared systems, changed systems)
        self._last_tick = _parse(last_tick) if last_tick else None
        self._seen = 0
        self.state_path = state_path            # set before the listener thread starts
        self._loaded = False
        self._saved_at: Optional[datetime] = None
        self._peak: Tuple[float, int, int, str] = (0.0, 0, 0, "")   # diagnostics, see snapshot()
        self._last_rates: Tuple[float, Optional[float]] = (0.0, None)

    def set_last_tick(self, tick: Optional[str]) -> None:
        """The newest known tick (from either source); keeps the 12 h gap honest."""
        t = _parse(tick) if tick else None
        if t and (self._last_tick is None or t > self._last_tick):
            self._last_tick = t

    # ── saved state ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        self._loaded = True
        if not self.state_path:
            return
        try:
            with gzip.open(self.state_path, "rt", encoding="utf-8") as f:
                data = json.load(f)
            self._history = {int(a): deque((_parse(t), lv) for t, lv in h) for a, h in data["history"].items()}
            self._hours = {_parse(h): (set(c), set(ch)) for h, (c, ch) in data["hours"].items()}
            log.info("Tick detector: reloaded %d systems, %d hours", len(self._history), len(self._hours))
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("Tick detector state not reloaded: %s", exc)

    def save(self, now: Optional[datetime] = None) -> None:
        """Writes the per-system readings and hourly shares (called on the listener thread)."""
        if not self.state_path:
            return
        now = now or datetime.now(timezone.utc)
        self._saved_at = now
        try:
            data = {"history": {str(a): [(_iso(t), lv) for t, lv in h] for a, h in self._history.items()
                                if h and now - h[-1][0] < FORGET},
                    "hours": {_iso(h): (sorted(c), sorted(ch)) for h, (c, ch) in self._hours.items()}}
            tmp = Path(str(self.state_path) + ".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=1) as f:   # ~50k systems: speed over size
                json.dump(data, f, separators=(",", ":"))
            tmp.replace(self.state_path)
        except Exception as exc:
            log.warning("Tick detector state not saved: %s", exc)

    # ── detection ─────────────────────────────────────────────────────────────
    def _baseline(self, now: datetime) -> Optional[float]:
        """Median share of changed systems over the earlier full hours."""
        current = _hour(now - WINDOW)
        rates = [len(ch) / len(c) for h, (c, ch) in sorted(self._hours.items())
                 if h < current and len(c) >= MIN_HOUR_SYSTEMS][-BASELINE_HOURS:]
        return statistics.median(rates) if len(rates) >= MIN_BASELINE_HOURS else None

    def _note(self, rate: float, n_changed: int, n_upl: int, outcome: str) -> None:
        if self._peak[3] != "(tick)" and rate >= self._peak[0]:   # a firing stays the reported one
            self._peak = (rate, n_changed, n_upl, outcome)

    def snapshot(self) -> str:
        """One log line: what was compared in the last hour, the share that
        changed against the usual share, and the strongest burst since the last
        call with what stopped it -- to tune RATIO from a real tick."""
        rate, base = self._last_rates
        peak = self._peak
        self._peak = (0.0, 0, 0, "")
        base_txt = f"{base:.1%}" if base is not None else "not yet"
        return (f"tick detector: {len(self._history)} systems tracked; last hour {rate:.1%} changed, "
                f"usual {base_txt} (fires at {RATIO:g}x); strongest {peak[0]:.1%} "
                f"({peak[1]} systems / {peak[2]} uploaders){' ' + peak[3] if peak[3] else ''}")

    def observe(self, system_address: Any, factions: List[dict], timestamp: str,
                now: Optional[datetime] = None, uploader: Optional[str] = None) -> Optional[str]:
        """Feed one message's Factions; returns the tick time (…Z) when this
        message completes a burst, else None."""
        if not self._loaded:
            self._load()
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
            self._hours = {h: v for h, v in self._hours.items() if now - h < timedelta(hours=24)}
        if self._saved_at is None or now - self._saved_at >= SAVE_EVERY:
            self.save(now)
        hist = self._history.setdefault(system_address, deque())
        # the settled reference: the newest reading at least REFERENCE_AGE old
        ref = next((lv for t, lv in reversed(hist) if ts - t >= REFERENCE_AGE), None)
        hist.append((ts, levels))
        while len(hist) > 2 and ts - hist[1][0] >= REFERENCE_AGE:
            hist.popleft()          # keep one reading older than the reference age, drop the rest
        if ref is None:
            return None
        changed = _moved(ref, levels)
        compared, moved = self._hours.setdefault(_hour(ts), (set(), set()))
        compared.add(system_address)
        if changed:
            moved.add(system_address)
        self._recent.append((ts, system_address, changed, uploader))
        while self._recent and ts - self._recent[0][0] > WINDOW:
            self._recent.popleft()
        if not changed:
            return None
        hour_systems = {r[1] for r in self._recent}
        if len(hour_systems) < MIN_HOUR_SYSTEMS:
            return None             # too few systems compared this hour to judge a share
        burst = [r for r in self._recent if r[2]]
        n_upl = len({r[3] for r in burst if r[3]})
        # the busiest uploader's changes don't count: one sender (EDDN is
        # unauthenticated) mustn't make the burst on its own
        by_upl: Dict[Any, set] = {}
        for r in burst:
            by_upl.setdefault(r[3], set()).add(r[1])
        top = max(by_upl, key=lambda u: len(by_upl[u]))
        n_changed = len({r[1] for r in burst if r[3] != top})
        rate = n_changed / len(hour_systems)
        base = self._baseline(ts)
        self._last_rates = (rate, base)
        if base is None:
            self._note(rate, n_changed, n_upl, "(learning the usual share)")
            return None
        if n_changed < MIN_CHANGED or n_upl < MIN_UPLOADERS or rate < RATIO * max(base, 0.001):
            self._note(rate, n_changed, n_upl, "")
            return None
        tick = min(r[0] for r in burst)
        if self._last_tick is not None and tick - self._last_tick < MIN_GAP:
            self._note(rate, n_changed, n_upl, "(too soon after the last tick)")
            return None
        self._note(rate, n_changed, n_upl, "(tick)")
        self._last_tick = tick
        return _iso(tick)
