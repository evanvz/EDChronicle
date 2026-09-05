"""Full-history scan to reconstruct currently-active missions at app
startup — same reasoning as bounty_scanner.py/squadron_scanner.py: a
mission can sit active for days, well outside the live bootstrap's
tail-replay window of the current journal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from edc.core.mission_events import MISSION_EVENT_NAMES, apply_mission_event, credit_massacre_kill

_SYSTEM_CHANGE_EVENTS = {"Location", "FSDJump", "CarrierJump"}
_RELEVANT_EVENT_NAMES = MISSION_EVENT_NAMES | _SYSTEM_CHANGE_EVENTS | {"Bounty", "FactionKillBond"}


def scan_active_missions(journal_dir: Path) -> Dict[int, Dict[str, Any]]:
    journal_dir = Path(journal_dir)
    active: Dict[int, Dict[str, Any]] = {}
    if not journal_dir.exists():
        return active

    current_system = None
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Mission' not in line and '"Bounty"' not in line and '"FactionKillBond"' not in line \
                            and '"Location"' not in line and '"FSDJump"' not in line and '"CarrierJump"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name not in _RELEVANT_EVENT_NAMES:
                        continue
                    if name in _SYSTEM_CHANGE_EVENTS:
                        current_system = event.get("StarSystem", current_system)
                    elif name in ("Bounty", "FactionKillBond"):
                        credit_massacre_kill(active, event.get("VictimFaction"), current_system)
                    else:
                        apply_mission_event(active, event)
        except OSError:
            continue

    return active
