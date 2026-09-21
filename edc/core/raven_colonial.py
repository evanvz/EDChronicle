# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Read-only client for Raven Colonial's public build-project API.

Raven Colonial (https://ravencolonial.com) is a community platform for
coordinating squad colonisation builds -- multiple commanders' clients each
push their own ColonisationConstructionDepot journal diffs to a shared
project record, aggregated server-side. EDChronicle's own colonisation_depots
table has no equivalent: ColonisationConstructionDepot has no EDDN schema,
so it's personal-only (confirmed via EDCD/EDDN's schema repo).

This client only reads -- see the GET-only endpoints below, confirmed live
and cross-referenced against njthomson/SrvSurvey's own RavenColonial.cs
client (GPL-3.0), which also pushes/writes; EDChronicle deliberately never
pushes our data to a third-party platform, so only the two GET endpoints it
uses are ported here.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
_TIMEOUT = 15

_BUILD_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def parse_build_id(text: str) -> Optional[str]:
    """Pulls a build UUID out of a raw id, or a pasted ravencolonial.com
    link (e.g. ".../#build=<uuid>")."""
    if not text:
        return None
    m = _BUILD_ID_RE.search(text)
    return m.group(0) if m else None


def get_project(build_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a build project by its Raven Colonial build id. None if not
    found or the request failed."""
    try:
        resp = requests.get(f"{_BASE_URL}/api/project/{build_id}", timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Raven Colonial project lookup failed for %r: %s", build_id, exc)
        return None


def get_project_for_station(system_address: int, market_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a build project by (system_address, market_id) -- the same
    identity our own colonisation_depots rows are keyed by. None if this
    station has no Raven Colonial project (a 404 is the expected/common
    case, not an error)."""
    try:
        resp = requests.get(f"{_BASE_URL}/api/system/{system_address}/{market_id}", timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(
            "Raven Colonial station lookup failed for system_address=%r market_id=%r: %s",
            system_address, market_id, exc,
        )
        return None
