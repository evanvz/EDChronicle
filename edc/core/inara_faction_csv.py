"""Parses a minor-faction system-presence CSV exported from Inara
(faction page -> export). Used to seed a bulk system list for the Player
Faction tab when a faction is present in hundreds of systems — too many
to add one at a time.

Expected header (Inara's actual export, confirmed against a real sample):
"Star system","Government","Allegiance","Power","Population","Fac","Sta","Inf","Updated"

Only Star system/Government/Allegiance/Power/Inf/Updated are used —
Population/Fac/Sta aren't faction-specific data. Notably, this export has
no BGS state (War/Election/Boom/...) and no controlling-system indicator;
callers needing those must still resolve each system properly (e.g. via
EDSM) rather than trusting this file alone for anything beyond a name +
influence starting point.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_RELATIVE_RE = re.compile(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)


def _parse_relative_date(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """'3 days ago' / '13 hours ago' / '56 minutes ago' -> ISO date string.
    Approximate (day-granularity downstream anyway, via snapshot_date)."""
    if not text:
        return None
    now = now or datetime.now()
    m = _RELATIVE_RE.search(text.strip())
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": timedelta(minutes=amount),
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
        "month": timedelta(days=amount * 30),
        "year": timedelta(days=amount * 365),
    }.get(unit)
    if delta is None:
        return None
    return (now - delta).date().isoformat()


def _parse_influence(text: str) -> Optional[float]:
    if not text:
        return None
    try:
        return float(text.strip().rstrip("%")) / 100.0
    except ValueError:
        return None


def parse_inara_faction_csv(path: Path) -> List[Dict[str, Any]]:
    """
    Returns a list of:
      {"system_name": str, "government": str, "allegiance": str,
       "power": str, "influence": float|None, "updated_date": str|None (ISO)}
    Skips rows with no system name. Raises on genuine file-read errors —
    caller should catch and report, this isn't a "return None on any
    problem" function like the network lookups.
    """
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            system_name = (raw.get("Star system") or "").strip()
            if not system_name:
                continue
            rows.append({
                "system_name": system_name,
                "government": (raw.get("Government") or "").strip() or None,
                "allegiance": (raw.get("Allegiance") or "").strip() or None,
                "power": (raw.get("Power") or "").strip() or None,
                "influence": _parse_influence(raw.get("Inf") or ""),
                "updated_date": _parse_relative_date(raw.get("Updated") or ""),
            })
    return rows
