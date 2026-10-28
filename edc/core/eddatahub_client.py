# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""EDDataHub: the squadron's own 24/7 BGS & PowerPlay service on the LAN
(C:\\Dev\\EDDataHub). It works out BGS ticks from its full EDDN archive
(tick.edcd.io when that has them, otherwise inferred -- calibrated to the same
placements as the feed for 94.4% of changes), so while it's reachable it is the
app's tick source; the app's own EDDN detection is the fallback. Read-only:
nothing of ours is sent to it."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from edc.version import USER_AGENT

log = logging.getLogger(__name__)

_TIMEOUT = 8
_MAX_TICKS = 100          # a 14-day answer holds ~15; more means a wrong or hostile answer


def fetch_ticks(base_url: str, days: int = 14) -> Optional[List[str]]:
    """The hub's galaxy ticks of the last `days`, oldest first, as ...Z strings;
    None when the hub isn't reachable or answers wrongly. Synchronous: call from
    a worker thread."""
    if not base_url:
        return None
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/ticks", params={"days": days},
                            headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list) or len(rows) > _MAX_TICKS:
            raise ValueError("not a tick list")
        now = datetime.now(timezone.utc)
        out = []
        for r in rows:
            t = datetime.fromisoformat(str(r["tick"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            # only ticks inside the window asked for: nothing future-dated or ancient
            if now - timedelta(days=days + 1) <= t <= now + timedelta(minutes=5):
                out.append(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return out
    except Exception as exc:
        log.info("EDDataHub not reachable (%s) -- using the app's own tick detection", exc)
        return None


def _z(value) -> str:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# the journal Factions[] fields EDDN carries; anything else in a hub answer is ignored
_FACTION_KEYS = ("Name", "Influence", "Government", "Allegiance", "FactionState", "Happiness",
                 "ActiveStates", "PendingStates", "RecoveringStates")


def _journal_state(s: str) -> str:
    """The hub spells states for reading ("Civil Unrest"); back to the journal's "CivilUnrest"."""
    return "Terrorism" if s == "Terrorist Attack" else s.replace(" ", "")


def fetch_system_factions(base_url: str, addresses: List[int]) -> Optional[dict]:
    """{system address: result} for the systems the hub has faction readings for, in
    edsm_faction_lookup.fetch_system_factions's shape (factions with is_controlling and
    LastUpdate) plus "conflicts" -- the real Conflicts entries, WonDays included.
    None when the hub isn't reachable or answers wrongly."""
    ids = [a for a in addresses if isinstance(a, int)]
    if not base_url or not ids:
        return None
    out = {}
    try:
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            resp = requests.get(f"{base_url.rstrip('/')}/api/system-factions",
                                params={"ids": ",".join(map(str, chunk))},
                                headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list) or len(rows) > len(chunk):
                raise ValueError("not a system faction list")
            wanted = set(chunk)
            for r in rows:
                if r.get("system") not in wanted or not isinstance(r.get("name"), str):
                    continue
                factions = []
                for f in r.get("factions") or []:
                    if not isinstance(f, dict) or not isinstance(f.get("Name"), str):
                        continue
                    rec = {k: f[k] for k in _FACTION_KEYS if k in f}
                    if isinstance(rec.get("FactionState"), str):
                        rec["FactionState"] = _journal_state(rec["FactionState"])
                    for k in ("ActiveStates", "PendingStates", "RecoveringStates"):
                        rec[k] = [{"State": _journal_state(s["State"])} for s in rec.get(k) or []
                                  if isinstance(s, dict) and isinstance(s.get("State"), str)]
                    rec["is_controlling"] = f["Name"] == r.get("controlling")
                    rec["LastUpdate"] = _z(f.get("updated") or r["updated"])
                    factions.append(rec)
                conflicts = [c for c in r.get("conflicts") or [] if isinstance(c, dict)]
                out[r["system"]] = {"system_address": r["system"], "system_name": r["name"],
                                    "factions": factions, "conflicts": conflicts,
                                    "updated": _z(r["updated"])}
        return out
    except Exception as exc:
        log.info("EDDataHub system factions not available (%s) -- using EDSM", exc)
        return None


def fetch_system_powerplay(base_url: str, addresses: List[int], since: str) -> Optional[dict]:
    """{system address: [reading, ...]} oldest first, every requested address a key ([] when
    the hub has no rows). A reading is {observed_at, pp_state, reinforcement, undermining,
    control, source: "hub"}. None when the hub isn't reachable or answers wrongly."""
    ids = [a for a in addresses if isinstance(a, int)]
    if not base_url or not ids:
        return None
    out = {a: [] for a in ids}
    try:
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            resp = requests.get(f"{base_url.rstrip('/')}/api/system-powerplay",
                                params={"ids": ",".join(map(str, chunk)), "since": since},
                                headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                raise ValueError("not a system powerplay list")
            wanted = set(chunk)
            for r in rows:
                if not isinstance(r, dict) or r.get("system") not in wanted:
                    continue
                out[r["system"]].append({"observed_at": _z(r["time"]), "pp_state": r.get("state"),
                                         "reinforcement": r.get("reinforcement"),
                                         "undermining": r.get("undermining"),
                                         "control": r.get("control"), "source": "hub"})
        return out
    except Exception as exc:
        log.info("EDDataHub system powerplay not available (%s)", exc)
        return None


_SEARCH_TIMEOUT = 3
_SEARCH_SKIP_S = 60
_skip_until = 0.0


def fetch_market_search(base_url: str, commodities: List[str], x: float, y: float, z: float,
                        radius: float, exclude_market_id: Optional[int] = None) -> Optional[List[dict]]:
    """The hub's market-search rows (see /api/market-search). None on any failure or while
    skipping the hub for _SEARCH_SKIP_S after a failure."""
    global _skip_until
    if not base_url or time.monotonic() < _skip_until:
        return None
    params = {"commodity": ",".join(commodities), "x": x, "y": y, "z": z, "radius": radius}
    if exclude_market_id is not None:
        params["exclude"] = exclude_market_id
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/market-search", params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=_SEARCH_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            raise ValueError("not a market search list")
        return rows
    except Exception as exc:
        _skip_until = time.monotonic() + _SEARCH_SKIP_S
        log.warning("EDDataHub market search failed (%s) -- skipping the hub for %d s", exc, _SEARCH_SKIP_S)
        return None


def fetch_markets(base_url: str, since: str, on_message, cancelled=lambda: False) -> Optional[int]:
    """The newest market (EDDN commodity/3 message body) of every station the hub
    received since `since` (it reads at most 7 days back), each passed to
    on_message as it streams in. The count, or None when the hub isn't reachable."""
    if not base_url:
        return None
    count = 0
    try:
        with requests.get(f"{base_url.rstrip('/')}/api/markets", params={"since": since},
                          headers={"User-Agent": USER_AGENT}, stream=True, timeout=(_TIMEOUT, 120)) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if cancelled():
                    break
                msg = json.loads(line) if line else None
                if isinstance(msg, dict) and isinstance(msg.get("marketId"), int) \
                        and isinstance(msg.get("commodities"), list):
                    on_message(msg)
                    count += 1
        return count
    except Exception as exc:
        log.info("EDDataHub markets not available (%s)", exc)
        return None if count == 0 else count


def fetch_system_ticks(base_url: str, addresses: List[int], days: int = 14) -> Optional[List[tuple]]:
    """When each tick reached these systems: [(system address, tick, last_before,
    first_after, status)] -- first_after is the first report with the tick's values.
    None when the hub isn't reachable or answers wrongly."""
    ids = [a for a in addresses if isinstance(a, int)][:50]
    if not base_url or not ids:
        return None
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/system-ticks",
                            params={"ids": ",".join(map(str, ids)), "days": days},
                            headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list) or len(rows) > len(ids) * (days + 2):
            raise ValueError("not a system tick list")
        wanted = set(ids)
        return [(r["system"], _z(r["tick"]), _z(r["last_before"]), _z(r["first_after"]), str(r["status"]))
                for r in rows if r.get("system") in wanted]
    except Exception as exc:
        log.info("EDDataHub system ticks not available (%s)", exc)
        return None
