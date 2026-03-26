import json
from pathlib import Path
from datetime import datetime, timezone

class SessionLedger:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return self._default()
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._default()
            base = self._default()
            base.update(data)
            return base
        except Exception:
            return self._default()

    def save(self, data: dict) -> None:
        payload = self._default()
        if isinstance(data, dict):
            payload.update(data)
        payload["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _default(self) -> dict:
        return {
            "combat_unsold_total": 0,
            "exploration_unsold_total_est": 0,
            "exobiology_unsold_total_est": 0,
            "last_updated": None,
        }