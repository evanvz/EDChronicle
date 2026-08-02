"""On-demand EDSM system-factions lookup — used when manually adding a
system to the Player Faction tab, to get real current faction data
immediately instead of waiting on EDDN network traffic (EDDN only reports
sightings as they happen live; there's no way to ask it about a specific
system directly).

Same EDSM data source as edsm_powerplay.py, same reason cloudscraper is
needed (Cloudflare's generic bot challenge in front of data EDSM already
publishes for third-party tools). This is a targeted per-system query
(fast, small response) rather than the ~20MB PowerPlay dump, so it's fine
to call synchronously from a worker thread per user action rather than
caching to disk.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import cloudscraper

log = logging.getLogger(__name__)

_FACTIONS_URL = "https://www.edsm.net/api-system-v1/factions"
_TIMEOUT = 20

# Second element of the return tuple when the first is None — lets the UI
# distinguish "genuinely not in EDSM's database" from "the request itself
# failed" (blocked/timed out/network error), which is not a spelling issue
# and was previously shown with the same misleading message.
ERROR_BLOCKED = "blocked"
ERROR_NOT_FOUND = "not_found"


def fetch_system_factions(system_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Synchronous — call from a worker thread only, never the UI thread.

    Returns ({"system_address": int, "system_name": str, "factions": [...]}, None)
    on success, or (None, ERROR_BLOCKED | ERROR_NOT_FOUND) on failure.
    Each entry in "factions" is normalized to the same shape as a raw
    journal Factions[] entry (Name/Influence/FactionState/ActiveStates/
    PendingStates/...) plus an "is_controlling" bool, so it can be passed
    straight into Repository.save_faction_snapshot.
    """
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(
            _FACTIONS_URL, params={"systemName": system_name, "showHistory": 0}, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("EDSM system-factions lookup failed for %r: %s", system_name, exc)
        return None, ERROR_BLOCKED

    if not isinstance(data, dict):
        return None, ERROR_BLOCKED

    system_address = data.get("id64")
    resolved_name = data.get("name")
    raw_factions = data.get("factions")
    if not (isinstance(system_address, int) and isinstance(resolved_name, str) and isinstance(raw_factions, list)):
        # A valid (non-blocked) response for an unknown system is an empty
        # dict/object from EDSM, not an HTTP error — that's the genuine
        # "not in EDSM's database" case. Logging the raw body here too,
        # since an unexpected-but-non-empty shape would otherwise look
        # identical to a real "not found" with no way to tell them apart.
        log.warning("EDSM response for %r missing expected fields — raw body: %r", system_name, data)
        return None, ERROR_NOT_FOUND

    controlling = data.get("controllingFaction")
    controlling_name = controlling.get("name") if isinstance(controlling, dict) else None

    factions: List[Dict[str, Any]] = []
    for f in raw_factions:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        if not isinstance(name, str) or not name:
            continue
        factions.append({
            "Name": name,
            "Influence": f.get("influence"),
            "Government": f.get("government"),
            "Allegiance": f.get("allegiance"),
            "FactionState": f.get("state"),
            "Happiness_Localised": f.get("happiness"),
            "ActiveStates": _states_to_journal_shape(f.get("activeStates")),
            "PendingStates": _states_to_journal_shape(f.get("pendingStates")),
            "RecoveringStates": _states_to_journal_shape(f.get("recoveringStates")),
            "is_controlling": bool(controlling_name and name == controlling_name),
        })

    return {"system_address": system_address, "system_name": resolved_name, "factions": factions}, None


def _states_to_journal_shape(states: Any) -> List[Dict[str, str]]:
    if not isinstance(states, list):
        return []
    out = []
    for s in states:
        if isinstance(s, dict) and s.get("state"):
            out.append({"State": s["state"]})
    return out
