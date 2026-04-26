from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging

log = logging.getLogger(__name__)


@dataclass
class PowerPlayActivity:
    action:        str
    ethos:         str
    bonus_powers:  List[str] = field(default_factory=list)
    contested_only: bool = False
    merits:        str = "yes"   # "yes" | "no" | "suspended"
    platform:      str = "ED"    # "ED" | "Odyssey"
    notes:         str = ""


class PowerPlayActivityTable:
    def __init__(self, types: Dict[str, List[PowerPlayActivity]], power_ethos: Dict | None = None):
        self.types = types
        self._power_ethos: Dict = power_ethos or {}

    @staticmethod
    def load_from_paths(*paths: Path) -> Optional["PowerPlayActivityTable"]:
        for p in paths:
            try:
                if not p.exists():
                    continue

                data = json.loads(p.read_text(encoding="utf-8"))
                types: Dict[str, List[PowerPlayActivity]] = {}

                for entry in data.get("system_types", []):
                    sys_type = entry.get("type")
                    if not sys_type:
                        continue
                    acts = []
                    for a in entry.get("activities", []):
                        acts.append(PowerPlayActivity(
                            action=a.get("action", ""),
                            ethos=a.get("ethos", ""),
                            bonus_powers=list(a.get("bonus_powers") or []),
                            contested_only=bool(a.get("contested_only", False)),
                            merits=str(a.get("merits", "yes")),
                            platform=str(a.get("platform", "ED")),
                            notes=str(a.get("notes", "")),
                        ))
                    types[sys_type] = acts

                power_ethos = data.get("power_ethos", {})
                log.info("Loaded PowerPlay activities from %s (%d system types)", p, len(types))
                return PowerPlayActivityTable(types, power_ethos)

            except Exception as e:
                log.warning("Failed loading PowerPlay activities from %s: %s", p, e)

        return None

    def get_actions(self, system_type: str, pp_state: str = "") -> List[PowerPlayActivity]:
        acts = self.types.get(system_type, [])
        if system_type == "acquisition" and (pp_state or "").lower() != "contested":
            acts = [a for a in acts if not a.contested_only]
        return acts

    def get_power_ethos(self, power: str, system_type: str) -> str:
        return self._power_ethos.get(power, {}).get(system_type, "")

    def is_defensive(self, system_type: str) -> bool:
        return system_type == "reinforcement"
