import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("edc.market_destination")


class MarketDestinationStore:
    """
    Persists the currently "pinned" buy/sell destination selected on the
    Market tab, so it survives an app or game crash — reopening after a
    crash mid-trip shows the same destination again instead of losing it.

    File location:
      <data_dir>/market_destination.json

    Format:
      {"system_name": str, "station_name": str, "commodity": str,
       "mode": "buy"|"sell", "pinned_at": iso timestamp}
    Absent/empty file means no destination is currently pinned.
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to load market destination")
            return None
        if not isinstance(data, dict):
            return None
        system_name = data.get("system_name")
        station_name = data.get("station_name")
        if not isinstance(system_name, str) or not system_name:
            return None
        if not isinstance(station_name, str) or not station_name:
            return None
        return {
            "system_name": system_name,
            "station_name": station_name,
            "commodity": data.get("commodity") if isinstance(data.get("commodity"), str) else "",
            "mode": data.get("mode") if data.get("mode") in ("buy", "sell") else "sell",
            "pinned_at": data.get("pinned_at") if isinstance(data.get("pinned_at"), str) else "",
        }

    def save(self, system_name: str, station_name: str, commodity: str, mode: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({
                    "system_name": system_name,
                    "station_name": station_name,
                    "commodity": commodity,
                    "mode": mode if mode in ("buy", "sell") else "sell",
                    "pinned_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save market destination")

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            log.exception("Failed to clear market destination")
