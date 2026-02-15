import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("edc.exo_values")


@dataclass(frozen=True)
class ExoSpeciesValue:
    species: str
    genus: str
    base_value: int
    ccr_m: int | None = None

class ExoValueTable:
    def __init__(self, by_species: Dict[str, ExoSpeciesValue]):
        self.by_species = by_species

    @staticmethod
    def load_from_paths(*paths: Path) -> Optional["ExoValueTable"]:
        for p in paths:
            try:
                if p and p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    species_map = data.get("species") or {}
                    out: Dict[str, ExoSpeciesValue] = {}
                    for name, rec in species_map.items():
                        if not isinstance(name, str) or not isinstance(rec, dict):
                            continue
                        bv = rec.get("base_value")
                        gn = rec.get("genus") or ""
                        ccr = rec.get("ccr_m")
                        if isinstance(bv, int) and gn:
                            out[name] = ExoSpeciesValue(species=name, genus=gn, base_value=bv, ccr_m=ccr)
                    if out:
                        log.info("Loaded exo values from %s (%d species)", p, len(out))
                        return ExoValueTable(out)
            except Exception:
                log.exception("Failed to load exo values from %s", p)
        return None

    def get_value(self, species_localised: str) -> Optional[int]:
        if not species_localised:
            return None
        rec = self.by_species.get(species_localised)
        return rec.base_value if rec else None
