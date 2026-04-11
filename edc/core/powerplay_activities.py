from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging

log = logging.getLogger(__name__)


@dataclass
class PowerPlayActivity:
    action: str
    ethos: str


class PowerPlayActivityTable:
    def __init__(
        self,
        states: Dict[str, List[PowerPlayActivity]],
        state_mapping: Dict[str, str] | None = None,
    ):
        self.states = states
        self.state_mapping = state_mapping or {}

    @staticmethod
    def load_from_paths(*paths: Path) -> Optional["PowerPlayActivityTable"]:
        for p in paths:
            try:
                if not p.exists():
                    continue

                data = json.loads(p.read_text(encoding="utf-8"))

                states: Dict[str, List[PowerPlayActivity]] = {}

                for entry in data.get("system_states", []):
                    state = entry.get("state")
                    acts = []

                    for a in entry.get("activities", []):
                        acts.append(
                            PowerPlayActivity(
                                action=a.get("action", ""),
                                ethos=a.get("ethos", ""),
                            )
                        )

                    states[state] = acts

                state_mapping = data.get("state_mapping", {})

                log.info(
                    "Loaded PowerPlay activities from %s (%d states)",
                    p, len(states)
                )
                return PowerPlayActivityTable(states, state_mapping)

            except Exception as e:
                log.warning("Failed loading PowerPlay activities from %s: %s", p, e)

        return None

    def get_actions(self, state: str) -> List[PowerPlayActivity]:
        mapped = self.state_mapping.get(state, state)
        return self.states.get(mapped, [])