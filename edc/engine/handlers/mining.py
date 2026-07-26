from __future__ import annotations
from typing import Any, Dict, List

# Fields per the official Journal Manual (§7.1 AsteroidCracked, §7.7
# MiningRefined, §13.25 LaunchDrone, §13.33 ProspectedAsteroid).


def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Mining session tracking (core/laser + prospector/limpet workflow).
    Returns True if handled.
    """

    if name == "ProspectedAsteroid":
        engine.state.mining_prospected_count += 1
        materials = event.get("Materials")
        engine.state.mining_last_prospect_materials = materials if isinstance(materials, list) else []
        content = event.get("Content")
        engine.state.mining_last_prospect_content = content if isinstance(content, str) and content else None
        motherlode = event.get("MotherlodeMaterial")
        engine.state.mining_last_motherlode_material = motherlode if isinstance(motherlode, str) and motherlode else None
        return True

    elif name == "MiningRefined":
        cargo_type = event.get("Type")
        if isinstance(cargo_type, str) and cargo_type:
            key = cargo_type.strip().lower()
            engine.state.mining_refined_totals[key] = engine.state.mining_refined_totals.get(key, 0) + 1
        return True

    elif name == "AsteroidCracked":
        engine.state.mining_cracked_count += 1
        return True

    return False
