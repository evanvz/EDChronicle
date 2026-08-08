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

    Also tracks the last Inara CSV import — EDSM can confirm a tracked
    system's faction is still present or has retreated, but has no way to
    discover systems the faction has newly expanded into; that only comes
    from re-exporting/re-importing the faction's Inara CSV, so a separate
    timestamp nudges the user to redo that periodically.

    File location: <data_dir>/faction_refresh.json — both timestamps share
    one file, so reads/writes always merge rather than overwrite the other.
    """

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            log.exception("Failed to load faction refresh tracker")
            return {}

    def _read_timestamp(self, key: str) -> Optional[datetime]:
        ts = self._read().get(key)
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                log.exception("Failed to parse %s", key)
        return None

    def _write_timestamp(self, key: str) -> None:
        try:
            data = self._read()
            data[key] = datetime.now(timezone.utc).isoformat()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            log.exception("Failed to save faction refresh tracker")

    def last_refresh(self) -> Optional[datetime]:
        return self._read_timestamp("last_refresh")

    def mark_refreshed(self) -> None:
        self._write_timestamp("last_refresh")

    def last_csv_import(self) -> Optional[datetime]:
        return self._read_timestamp("last_csv_import")

    def mark_csv_imported(self) -> None:
        self._write_timestamp("last_csv_import")
