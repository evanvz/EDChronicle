# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("edc.faction_expansion_pin")


class FactionExpansionPinStore:
    """
    Persists the system currently being tracked on the Faction Expansion
    window, so it survives an app restart -- same shape as
    RavenColonialPinStore/MarketDestinationStore.

    File location:
      <data_dir>/faction_expansion_pin.json

    Format:
      {"system_name": str, "pinned_at": iso timestamp}
    Absent/empty file means nothing is currently pinned.
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Optional[str]:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to load faction expansion pin")
            return None
        if not isinstance(data, dict):
            return None
        system_name = data.get("system_name")
        return system_name if isinstance(system_name, str) and system_name else None

    def save(self, system_name: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({
                    "system_name": system_name,
                    "pinned_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save faction expansion pin")

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            log.exception("Failed to clear faction expansion pin")
