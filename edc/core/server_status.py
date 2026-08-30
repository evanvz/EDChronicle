"""Elite Dangerous server status -- polls Frontier's own status endpoint.

Unlike the EDSM/EDDN/BGS Tick indicators in the status bar (inferred
passively from warnings already flowing through our own logging -- see
service_health.py), server status can't be inferred that way: "no errors
yet" and "Frontier's servers are down" look identical from here. This
needs a real periodic check against Frontier's own endpoint instead.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

log = logging.getLogger(__name__)

_STATUS_URL = "https://ed-server-status.orerve.net/"
_TIMEOUT = 10
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


def fetch_server_status() -> Tuple[Optional[str], Optional[str]]:
    """Returns (status, message), e.g. ("Good", "") -- or (None, None) on
    any failure (network error, bad response shape). Synchronous -- call
    from a worker thread, never the UI thread."""
    try:
        resp = requests.get(_STATUS_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Elite Dangerous server status check failed: %s", exc)
        return None, None

    if not isinstance(data, dict):
        return None, None
    status = data.get("status")
    message = data.get("message") or ""
    return (status if isinstance(status, str) and status else None), message
