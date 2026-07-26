import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.engineering_blueprints")


class EngineeringBlueprintTable:
    """
    Offline, advisory-only engineering blueprint recipe reference.
    Sourced from EDCD/coriolis-data + EDCD/FDevIDs (MIT licensed).

    File location (portable-in-repo):
      <settings_dir>/engineering_blueprints.json

    Expected format:
      {
        "last_updated": "YYYY-MM-DD",
        "blueprints": {
          "<fdname>": {
            "display_name": "Frame shift drive",
            "short_name": "Increased Range",
            "grades": {
              "1": {"<material_symbol_lower>": <qty>, ...},
              ...
              "5": {...}
            }
          }
        }
      }

    Material keys use the same lowercase internal symbol convention as
    GameState.materials_raw/manufactured/encoded, so requirements can be
    diffed against live inventory directly with no name translation.
    """

    def __init__(self, settings_dir: Path, filename: str = "engineering_blueprints.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._blueprints: Dict[str, Dict[str, Any]] = {}
        self._materials: Dict[str, Dict[str, Any]] = {}
        self._load(force=True)

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._blueprints = {}
                self._materials = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = None
            blueprints = {}
            materials = {}
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = lu.strip() if isinstance(lu, str) and lu.strip() else None
                blueprints = data.get("blueprints") or {}
                materials = data.get("materials") or {}

            self._blueprints = blueprints if isinstance(blueprints, dict) else {}
            self._materials = materials if isinstance(materials, dict) else {}
        except Exception:
            log.exception("Failed to load engineering_blueprints.json")
            self._blueprints = {}
            self._materials = {}
            self.last_updated = None
            self._mtime = None

    def has_data(self) -> bool:
        self._load(force=False)
        return bool(self._blueprints)

    def blueprint_names(self) -> List[str]:
        """Returns fdnames sorted by display_name, for populating a picker."""
        self._load(force=False)
        return sorted(
            self._blueprints.keys(),
            key=lambda k: (self._blueprints[k].get("display_name") or k),
        )

    def get(self, fdname: str) -> Optional[Dict[str, Any]]:
        self._load(force=False)
        return self._blueprints.get(fdname)

    def requirements(self, fdname: str, grade: int) -> Dict[str, int]:
        """Returns {material_symbol_lower: qty} for one blueprint grade, or {} if unknown."""
        bp = self.get(fdname)
        if not bp:
            return {}
        grades = bp.get("grades") or {}
        reqs = grades.get(str(grade))
        return dict(reqs) if isinstance(reqs, dict) else {}

    def max_grade(self, fdname: str) -> int:
        bp = self.get(fdname)
        if not bp:
            return 0
        grades = bp.get("grades") or {}
        try:
            return max(int(g) for g in grades.keys())
        except ValueError:
            return 0

    def material_name(self, symbol: str) -> str:
        """Player-facing display name for a material symbol, falling back to the symbol itself."""
        self._load(force=False)
        rec = self._materials.get(symbol.lower()) if isinstance(symbol, str) else None
        return rec.get("name", symbol) if isinstance(rec, dict) else symbol

    def material_type(self, symbol: str) -> str:
        """Raw / Manufactured / Encoded, or "" if unknown."""
        self._load(force=False)
        rec = self._materials.get(symbol.lower()) if isinstance(symbol, str) else None
        return rec.get("type", "") if isinstance(rec, dict) else ""
