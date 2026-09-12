# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

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
        if isinstance(materials, list):
            # Name is the raw "$xxx_name;"-free internal symbol -- still not
            # the display name Frontier shows in-game (e.g. "lowtemperaturediamonds"
            # vs "Low Temperature Diamonds"). Prefer Name_Localised, same
            # reasoning as MiningRefined's Type/Type_Localised below.
            materials = [
                {**m, "Name": m.get("Name_Localised") or m.get("Name")}
                if isinstance(m, dict) else m
                for m in materials
            ]
        engine.state.mining_last_prospect_materials = materials if isinstance(materials, list) else []
        content = event.get("Content_Localised") or event.get("Content")
        engine.state.mining_last_prospect_content = content if isinstance(content, str) and content else None
        motherlode = event.get("MotherlodeMaterial_Localised") or event.get("MotherlodeMaterial")
        engine.state.mining_last_motherlode_material = motherlode if isinstance(motherlode, str) and motherlode else None
        return True

    elif name == "MiningRefined":
        # Type is the raw internal symbol (e.g. "$lepidolite_name;") -- the
        # journal always pairs it with Type_Localised (e.g. "Lepidolite"),
        # confirmed live: showing Type directly rendered as "$Lepidolite_Name;"
        # once the UI's .title() call ran over the unstripped raw token.
        cargo_type = event.get("Type_Localised") or event.get("Type")
        if isinstance(cargo_type, str) and cargo_type:
            key = cargo_type.strip().lower()
            engine.state.mining_refined_totals[key] = engine.state.mining_refined_totals.get(key, 0) + 1
        return True

    elif name == "AsteroidCracked":
        engine.state.mining_cracked_count += 1
        return True

    return False
