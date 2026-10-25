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

import logging
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
