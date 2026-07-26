import json
import logging
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger("edc.engineer_progress_store")


class EngineerProgressStore:
    """
    Persists last-known engineer unlock status across app restarts.

    Why: the live journal-tail bootstrap only replays a small tail window
    of the active journal (see journal_watcher.py's _bootstrap_newest_system,
    last ~256KB / newest-system-only) — the one-time EngineerProgress
    roster summary fires at game login and scrolls out of that window
    well before a typical play session ends. Without persisting it,
    restarting EDChronicle mid-session (without restarting the game)
    would show every engineer as "Not encountered" until the next login.

    File location:
      <data_dir>/engineer_progress.json

    Format:
      {"engineers": {"<name>": {"engineer_id": int, "rank": int|None,
                                  "progress": str, "rank_progress": int|None}}}
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            engineers = data.get("engineers") if isinstance(data, dict) else None
            return engineers if isinstance(engineers, dict) else {}
        except Exception:
            log.exception("Failed to load engineer_progress.json")
            return {}

    def save(self, engineers: Dict[str, Dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"engineers": engineers}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save engineer_progress.json")
