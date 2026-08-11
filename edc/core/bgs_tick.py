"""BGS tick detection via tick.edcd.io -- a free public community service
that detects and timestamps the game's actual daily BGS tick (faction
state recalculation), instead of approximating it via a calendar-day
boundary. Confirmed live: GET /api/tick returns a bare JSON string like
"2026-08-11T10:51:03+00:00", no auth, no documented rate limit.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

_TICK_URL = "https://tick.edcd.io/api/tick"
_TIMEOUT = 10
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


def fetch_latest_tick() -> Optional[str]:
    """
    Returns the most recently detected BGS tick as an ISO8601 UTC
    timestamp string, or None on any failure -- network error, timeout,
    bad/unexpected response shape. Call from a worker thread only, never
    the UI thread.
    """
    try:
        resp = requests.get(_TICK_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Failed to fetch latest BGS tick: %s", exc)
        return None
    if not isinstance(data, str) or not data:
        return None
    return data
