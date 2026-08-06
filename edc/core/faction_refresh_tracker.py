import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("edc.faction_refresh_tracker")


class FactionRefreshTracker:
    """
    Tracks when the Player Faction tab's full EDSM refresh (every known
    system, every faction present there — not just the squadron-aligned
    one) last completed, so it runs about once a day rather than on every
    startup. Once-a-day matches the BGS's own daily tick — refreshing more
    often wouldn't reveal anything new.

    File location: <data_dir>/faction_refresh.json
    """

    def __init__(self, path: Path):
        self.path = path

    def last_refresh(self) -> Optional[datetime]:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            ts = data.get("last_refresh")
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            log.exception("Failed to load faction refresh tracker")
        return None

    def mark_refreshed(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"last_refresh": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save faction refresh tracker")
