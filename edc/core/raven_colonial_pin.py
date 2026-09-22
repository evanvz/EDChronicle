# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("edc.raven_colonial_pin")


class RavenColonialPinStore:
    """
    Persists the last successfully-loaded Raven Colonial build id, so the
    dialog reopens showing the same squad build across an app restart
    instead of needing the link pasted in again every time.

    File location:
      <data_dir>/raven_colonial_pin.json

    Format:
      {"build_id": str, "pinned_at": iso timestamp}
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
            log.exception("Failed to load Raven Colonial pin")
            return None
        if not isinstance(data, dict):
            return None
        build_id = data.get("build_id")
        return build_id if isinstance(build_id, str) and build_id else None

    def save(self, build_id: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({
                    "build_id": build_id,
                    "pinned_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save Raven Colonial pin")

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            log.exception("Failed to clear Raven Colonial pin")
