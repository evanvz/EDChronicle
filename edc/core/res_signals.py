"""Shared RES-tier parsing for FSSSignalDiscovered's ResourceExtraction
signals -- used by both the live event engine (own journal, event_engine.py)
and eddn_listener.py (network-wide), so the two can't drift."""
from __future__ import annotations

import re

_TIER_RE = re.compile(r"\[(Low|High|Hazardous)\]", re.IGNORECASE)


def res_tier_from_signal_name(signal_name: str) -> str:
    """'Resource Extraction Site [Hazardous]' -> 'Hazardous'.
    A plain 'Resource Extraction Site' (no bracket) -> 'Nominal'."""
    if not isinstance(signal_name, str):
        return "Nominal"
    m = _TIER_RE.search(signal_name)
    return m.group(1).title() if m else "Nominal"
