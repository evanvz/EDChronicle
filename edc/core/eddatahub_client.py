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
from datetime import datetime, timezone
from typing import List, Optional

import requests

from edc.version import USER_AGENT

log = logging.getLogger(__name__)

DEFAULT_URL = "http://172.16.10.197:8080"
_TIMEOUT = 8


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
        out = []
        for r in rows:
            t = datetime.fromisoformat(str(r["tick"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            out.append(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return out
    except Exception as exc:
        log.info("EDDataHub not reachable (%s) -- using the app's own tick detection", exc)
        return None
