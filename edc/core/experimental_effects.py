import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("edc.experimental_effects")


class ExperimentalEffectsTable:
    """
    Offline, advisory-only reference for Experimental Effects — the optional
    secondary modifier applicable at an Engineer alongside a primary
    blueprint, each with its own flat (non-grade-scaling) material cost.

    File location (portable-in-repo):
      <settings_dir>/experimental_effects.json

    Sourced from EDCD/coriolis-data (modifications/specials.json) +
    EDCD/FDevIDs (material.csv) — Frontier game data, non-commercial fan
    use. Component keys use the same lowercase internal symbol convention
    as GameState.materials_raw/manufactured/encoded.

    No compatibility data exists (which effects are valid for which module
    type) — every effect is listed for every blueprint, same as the
    existing engineer-coverage list elsewhere in this app: incomplete
    coverage is shown as unknown, not hidden.
    """

    def __init__(self, settings_dir: Path, filename: str = "experimental_effects.json"):
        self.path = Path(settings_dir) / filename
        self.last_updated: Optional[str] = None
        self._effects: Dict[str, Dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                self._effects = {}
                return
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.last_updated = data.get("last_updated")
            self._effects = data.get("effects", {})
        except Exception:
            log.exception("Failed to load experimental effects data from %s", self.path)
            self._effects = {}

    def effect_names(self) -> List[Tuple[str, str]]:
        """[(edname, display_name), ...] sorted by display name."""
        return sorted(
            ((edname, rec.get("name", edname)) for edname, rec in self._effects.items()),
            key=lambda pair: pair[1],
        )

    def display_name(self, edname: str) -> str:
        rec = self._effects.get(edname) or {}
        return rec.get("name", edname)

    def requirements(self, edname: str) -> Dict[str, int]:
        rec = self._effects.get(edname) or {}
        return dict(rec.get("components") or {})

    def has_known_cost(self, edname: str) -> bool:
        return bool(self.requirements(edname))
