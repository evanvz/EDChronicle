import json
import logging
from pathlib import Path
from typing import Set

log = logging.getLogger("edc.megaship_tracker")


class MegashipTracker:
    """
    Persists which specific megaships (keyed by system + their unique
    SignalName, e.g. "CAO-396 Beckett-class Researcher") have already been
    flagged for a PowerPlay merit scan — scanning the same megaship again
    doesn't grant merits again, and megaships can sit in a system for many
    days/sessions, so this needs to survive app restarts, not just resets
    per system-arrival like other signal dedup sets.
    """

    def __init__(self, path: Path):
        self.path = path
        self._seen: Set[str] = self._load()

    def _load(self) -> Set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            keys = data.get("seen") if isinstance(data, dict) else None
            return set(keys) if isinstance(keys, list) else set()
        except Exception:
            log.exception("Failed to load megaships_seen.json")
            return set()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"seen": sorted(self._seen)}, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            log.exception("Failed to save megaships_seen.json")

    @staticmethod
    def key(system_address, signal_name: str) -> str:
        return f"{system_address}|{signal_name}"

    def has_seen(self, key: str) -> bool:
        return key in self._seen

    def mark_seen(self, key: str) -> None:
        if key not in self._seen:
            self._seen.add(key)
            self._save()

    def merge_seen(self, keys: Set[str]) -> None:
        """Bulk-add (e.g. from a full journal-history scan at startup) — a
        single save regardless of how many new keys, not one per key."""
        new_keys = keys - self._seen
        if new_keys:
            self._seen.update(new_keys)
            self._save()
