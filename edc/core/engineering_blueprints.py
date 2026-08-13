import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.engineering_blueprints")

# Rolls needed to fully complete each grade, assuming max Engineer access
# level (rank 5) with the engineer doing the work. Elite Dangerous's 2018
# engineering rebalance made progress-per-roll deterministic (not random),
# but not flat 1-roll-per-grade: at access level 5 the progress-per-roll
# is 100%/50%/34%/25%/20% for grades 1-5 respectively (each roll consumes
# the grade's materials fresh), so grade 5 alone takes 5 applications, not
# 1. Source: the official per-grade/access-level progress table (Elite
# Dangerous Wiki, "Engineers" article). Lower access level needs more
# rolls (and some grades are locked outright) -- this assumes best-case
# max rank, not the player's actual current standing with any specific
# engineer.
_ROLLS_PER_GRADE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


class EngineeringBlueprintTable:
    """
    Offline, advisory-only engineering blueprint recipe reference.
    Sourced from EDCD/coriolis-data + EDCD/FDevIDs — Frontier game data,
    not the coriolis.io site code (which is separately MIT); used here
    non-commercially under Frontier's community/fan content terms.

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
            },
            "grade_engineers": {"1": ["Engineer Name", ...], ...}
          }
        },
        "engineer_locations": {
          "Engineer Name": {"id": <EngineerID>, "system_address": <id64>, "market_id": <int>}
        }
      }

    Material keys use the same lowercase internal symbol convention as
    GameState.materials_raw/manufactured/encoded, so requirements can be
    diffed against live inventory directly with no name translation.

    grade_engineers is sourced from msarilar/EDEngineer, joined onto the
    coriolis-data blueprints via each grade's UUID (~97% coverage — a
    blueprint/grade with no entry means unknown, not "no engineer offers
    it"). engineer_locations is EDCD/FDevIDs' engineers.csv.
    """

    def __init__(self, settings_dir: Path, filename: str = "engineering_blueprints.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._blueprints: Dict[str, Dict[str, Any]] = {}
        self._materials: Dict[str, Dict[str, Any]] = {}
        self._engineer_locations: Dict[str, Dict[str, Any]] = {}
        self._engineer_requirements: Dict[str, Dict[str, str]] = {}
        self._requirements_mtime: Optional[float] = None
        self._load(force=True)
        self._load_requirements(force=True)

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._blueprints = {}
                self._materials = {}
                self._engineer_locations = {}
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
            engineer_locations = {}
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = lu.strip() if isinstance(lu, str) and lu.strip() else None
                blueprints = data.get("blueprints") or {}
                materials = data.get("materials") or {}
                engineer_locations = data.get("engineer_locations") or {}

            self._blueprints = blueprints if isinstance(blueprints, dict) else {}
            self._materials = materials if isinstance(materials, dict) else {}
            self._engineer_locations = engineer_locations if isinstance(engineer_locations, dict) else {}
        except Exception:
            log.exception("Failed to load engineering_blueprints.json")
            self._blueprints = {}
            self._materials = {}
            self._engineer_locations = {}
            self.last_updated = None
            self._mtime = None

    def _load_requirements(self, force: bool = False) -> None:
        path = self.path.parent / "engineer_requirements.json"
        try:
            if not path.exists():
                self._engineer_requirements = {}
                self._requirements_mtime = None
                return

            m = path.stat().st_mtime
            if (not force) and (self._requirements_mtime is not None) and (m == self._requirements_mtime):
                return

            data = json.loads(path.read_text(encoding="utf-8"))
            self._requirements_mtime = m
            engineers = data.get("engineers") if isinstance(data, dict) else None
            self._engineer_requirements = engineers if isinstance(engineers, dict) else {}
        except Exception:
            log.exception("Failed to load engineer_requirements.json")
            self._engineer_requirements = {}
            self._requirements_mtime = None

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
        """Returns {material_symbol_lower: qty} for one single blueprint grade, or {} if unknown."""
        bp = self.get(fdname)
        if not bp:
            return {}
        grades = bp.get("grades") or {}
        reqs = grades.get(str(grade))
        return dict(reqs) if isinstance(reqs, dict) else {}

    def cumulative_requirements(self, fdname: str, grade: int) -> Dict[str, int]:
        """
        Returns {material_symbol_lower: qty} summed across grades 1..grade,
        each grade's materials multiplied by _ROLLS_PER_GRADE since each
        grade needs progressively more applications to fully complete (not
        1) — building at grade 5 needs grade 1's materials x1, grade 2's
        x2, ... grade 5's x5, combined, not just each grade's materials
        once each.
        """
        bp = self.get(fdname)
        if not bp:
            return {}
        grades = bp.get("grades") or {}
        total: Dict[str, int] = {}
        for g in range(1, grade + 1):
            reqs = grades.get(str(g))
            if not isinstance(reqs, dict):
                continue
            rolls = _ROLLS_PER_GRADE.get(g, 1)
            for material, qty in reqs.items():
                if isinstance(qty, int):
                    total[material] = total.get(material, 0) + qty * rolls
        return total

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

    def engineers_for(self, fdname: str, grade: int) -> List[str]:
        """Engineer names known to offer this blueprint at this grade (sourced from EDEngineer, joined via Coriolis blueprint UUID — coverage isn't 100%, so an empty list means unknown, not 'no one offers it')."""
        bp = self.get(fdname)
        if not bp:
            return []
        grade_engineers = bp.get("grade_engineers") or {}
        names = grade_engineers.get(str(grade))
        return list(names) if isinstance(names, list) else []

    def engineer_system_address(self, engineer_name: str) -> Optional[int]:
        """Home system id64 for a named engineer, or None if unknown."""
        self._load(force=False)
        rec = self._engineer_locations.get(engineer_name)
        addr = rec.get("system_address") if isinstance(rec, dict) else None
        return addr if isinstance(addr, int) else None

    def engineer_home(self, engineer_name: str) -> Optional[Dict[str, Any]]:
        """Returns {"system_name","x","y","z"} for a named engineer, or None if unknown."""
        self._load(force=False)
        rec = self._engineer_locations.get(engineer_name)
        if not isinstance(rec, dict) or "x" not in rec:
            return None
        return {
            "system_name": rec.get("system_name"),
            "x": rec.get("x"), "y": rec.get("y"), "z": rec.get("z"),
        }

    def engineer_requirements(self, engineer_name: str) -> Optional[Dict[str, str]]:
        """Returns the {"discover","meet","unlock","referral"} subset present
        for this engineer, or None if unknown. Missing fields are simply
        absent from the dict, not empty strings."""
        self._load_requirements(force=False)
        rec = self._engineer_requirements.get(engineer_name)
        return rec if isinstance(rec, dict) else None

    def all_engineer_names(self) -> List[str]:
        """Every known engineer name, sourced from engineer_locations (the
        superset -- every entry in engineer_requirements is expected to
        also appear here, per this file's join-key requirement)."""
        self._load(force=False)
        return sorted(self._engineer_locations.keys())

    def all_engineer_requirements(self) -> Dict[str, Dict[str, str]]:
        """Every engineer's requirements dict at once -- callers needing
        all engineers (e.g. a full reference list) should use this instead
        of calling engineer_requirements() in a per-engineer loop, to avoid
        a redundant file-mtime-check per engineer."""
        self._load_requirements(force=False)
        return dict(self._engineer_requirements)

    def all_engineer_homes(self) -> Dict[str, Dict[str, Any]]:
        """Every engineer's {"system_name","x","y","z"} at once -- same
        reasoning as all_engineer_requirements()."""
        self._load(force=False)
        return {
            name: {
                "system_name": rec.get("system_name"),
                "x": rec.get("x"), "y": rec.get("y"), "z": rec.get("z"),
            }
            for name, rec in self._engineer_locations.items()
            if isinstance(rec, dict) and "x" in rec
        }
