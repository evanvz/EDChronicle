import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger("edc.status_watcher")

class StatusWatcher(QObject):
    """
    Watches a single Status.json file (Elite Dangerous) and emits a dict whenever it changes.
    Intended to run in a QThread, like JournalWatcher.
    """

    event_received = pyqtSignal(dict)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, status_path: Path, poll_s: float = 0.2):
        super().__init__()
        self.status_path = status_path
        self.poll_s = poll_s
        self._running = False
        self._last_mtime: Optional[float] = None
        self._last_ts: Optional[str] = None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self.status.emit(f"Watching status: {self.status_path}")

        while self._running:
            try:
                if not self.status_path.exists():
                    time.sleep(1.0)
                    continue

                mtime = self.status_path.stat().st_mtime
                if self._last_mtime is not None and mtime == self._last_mtime:
                    time.sleep(self.poll_s)
                    continue
                self._last_mtime = mtime

                raw = self.status_path.read_text(encoding="utf-8", errors="replace")
                if not raw.strip():
                    time.sleep(self.poll_s)
                    continue

                try:
                    evt: Dict[str, Any] = json.loads(raw)
                except Exception as e:
                    self.error.emit(f"Status.json parse error: {e}")
                    time.sleep(self.poll_s)
                    continue

                # De-dupe: Status.json can update multiple times with same timestamp
                ts = str(evt.get("timestamp") or "")
                if ts and ts == self._last_ts:
                    time.sleep(self.poll_s)
                    continue
                if ts:
                    self._last_ts = ts

                # Ensure event name exists for engine
                if "event" not in evt:
                    evt["event"] = "Status"

                self.event_received.emit(evt)

            except Exception:
                log.exception("StatusWatcher loop error")
                time.sleep(1.0)

        self.status.emit("StatusWatcher stopped")
