# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

from __future__ import annotations
from typing import Any, Dict, List

def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Exobiology events (ScanOrganic / SellOrganicData).
    Returns True if handled.
    """

    if name == "ScanOrganic":
        # Store latest organic scan record
        body = event.get("BodyName")
        genus = event.get("Genus")
        species = event.get("Species")
        if isinstance(body, str) and body.strip():
            engine.state.last_body = body

        # Append scan event to exo session list (or update)
        engine.state.last_organic_scan = event

        # Value estimate (if table present)
        try:
            if engine.exo_values:
                val = engine.exo_values.estimate_value(event)
                engine.state.last_organic_value = val
        except Exception:
            pass

        # Lightweight UI message
        if isinstance(genus, str) and genus.strip():
            if isinstance(species, str) and species.strip():
                msgs.append(f"Exobio scan: {genus} / {species}")
            else:
                msgs.append(f"Exobio scan: {genus}")
        return True

    elif name == "SellOrganicData":
        # Session ledger: organic data sold
        total = event.get("BioDataValue")
        if isinstance(total, int):
            engine.state.session_exobio_earnings += total
            msgs.append(f"Exobio sold: {total:,} cr")
        return True

    return False