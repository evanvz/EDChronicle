"""Shared ring-name/hotspot parsing used by both the live event engine and
the historical journal importer, so the two stay in sync.

Rings are scanned as their own body in the journal (e.g. "HIP 110376 A 2 B
Ring"), separate from — and not always accompanied by — their parent's Scan
event carrying a "Rings" summary array (confirmed via live journal data:
already-discovered systems can omit that array entirely). Matching on the
ring's own body name is the reliable detection path.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

RING_NAME_RE = re.compile(r"^(.*) ([A-Za-z]) Ring$")


def parent_body_from_ring_name(ring_name: str) -> Optional[str]:
    match = RING_NAME_RE.match(ring_name)
    return match.group(1) if match else None


def parse_ring_hotspots(signals: Any) -> List[Dict[str, Any]]:
    """SAASignalsFound.Signals for a ring body is a list of hotspot
    materials (e.g. "Platinum"), not one of the Biological/Geological/
    Human/Thargoid/Other buckets used for planetary bodies."""
    hotspots: List[Dict[str, Any]] = []
    for sig in (signals or []):
        if not isinstance(sig, dict):
            continue
        mat_name = sig.get("Type_Localised") or sig.get("Type") or ""
        mat_count = sig.get("Count", 0)
        if mat_name and isinstance(mat_count, int):
            hotspots.append({"name": mat_name, "count": mat_count})
    return hotspots
