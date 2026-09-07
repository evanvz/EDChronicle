# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

from __future__ import annotations
from typing import Any, Dict, List

# Fields per the official Journal Manual (§8.15 EngineerProgress). Fired
# as a full-roster summary at startup (event has an "Engineers" array)
# and as a single-engineer update thereafter (fields at the top level).


def _apply_one(engine, rec: Dict[str, Any]) -> None:
    name = rec.get("Engineer")
    if not isinstance(name, str) or not name:
        return
    engine.state.engineer_progress[name] = {
        "engineer_id": rec.get("EngineerID"),
        "rank": rec.get("Rank"),
        "progress": rec.get("Progress"),
        "rank_progress": rec.get("RankProgress"),
    }


def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    if name != "EngineerProgress":
        return False

    roster = event.get("Engineers")
    if isinstance(roster, list):
        for rec in roster:
            if isinstance(rec, dict):
                _apply_one(engine, rec)
    else:
        _apply_one(engine, event)

    return True
