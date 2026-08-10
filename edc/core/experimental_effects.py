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

    coriolis-data doesn't dedupe by name: the same effect concept (e.g.
    "Stripped Down") has one entry per applicable module type, each with
    its own edname and material cost. The edname itself encodes that
    module type as a `special_<category>_...` prefix, which is matched
    against each blueprint's fdname prefix (e.g. "FSD_LongRange" ->
    "fsd") to filter the list down to what's actually valid for the
    selected blueprint — real data, not a hand-maintained guess.
    """

    # edname category token -> matching blueprint fdname prefix (lowercased).
    # A blueprint prefix with no entry here (AFM, CargoRack, Scanner, Misc,
    # utility mounts, etc.) genuinely has no Experimental Effects in-game.
    _BLUEPRINT_PREFIX_TO_CATEGORY = {
        "armour": "armour",
        "engine": "engine",
        "fsd": "fsd",
        "hullreinforcement": "hullreinforcement",
        "mc": "weapon",
        "powerdistributor": "powerdistributor",
        "powerplant": "powerplant",
        "shieldbooster": "shieldbooster",
        "shieldcellbank": "shieldcell",
        "shieldgenerator": "shield",
        "weapon": "weapon",
    }
    # Longest/most-specific category tokens must be checked before their
    # prefixes (e.g. "shieldbooster_" before "shield_") to avoid a false
    # match — order matters here.
    _EFFECT_CATEGORY_TOKENS = [
        "hullreinforcement", "powerdistributor", "powerplant",
        "shieldbooster", "shieldcell", "shield", "armour", "engine", "fsd",
    ]

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

    def _category(self, edname: str) -> str:
        rest = edname[len("special_"):] if edname.startswith("special_") else edname
        for token in self._EFFECT_CATEGORY_TOKENS:
            if rest.startswith(token + "_"):
                return token
        return "weapon"  # ammo/hardpoint effects (e.g. special_incendiary_rounds)

    def effect_names_for_blueprint(self, fdname: str) -> List[Tuple[str, str]]:
        """[(edname, display_name), ...] valid for this blueprint's module
        type, sorted by display name — empty if that module type has no
        Experimental Effects at all."""
        prefix = (fdname or "").split("_", 1)[0].lower()
        category = self._BLUEPRINT_PREFIX_TO_CATEGORY.get(prefix)
        if category is None:
            return []
        return [
            (edname, label) for edname, label in self.effect_names()
            if self._category(edname) == category
        ]
