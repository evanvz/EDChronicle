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
