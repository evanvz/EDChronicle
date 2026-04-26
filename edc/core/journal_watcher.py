import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger("edc.journal_watcher")

class JournalWatcher(QObject):
    event_received = pyqtSignal(dict)     # emits raw event dict
    status = pyqtSignal(str)             # emits human status messages
    error = pyqtSignal(str)              # emits readable error message

    def __init__(self, journal_dir: Path):
        super().__init__()
        self.journal_dir = journal_dir
        self._running = False
        self._current_file: Optional[Path] = None
        self._fp = None
        self._no_journal_notice = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """
        Call this in a worker thread. Never touch UI directly from here.
        """
        self._running = True
        self.status.emit(f"Watching: {self.journal_dir}")

        while self._running:
            try:
                latest = self._find_latest_journal(self.journal_dir)
                if latest is None:
                    if not self._no_journal_notice:
                        self.status.emit("No Journal*.log found yet...")
                        self._no_journal_notice = True
                    time.sleep(1.0)
                    continue
                self._no_journal_notice = False

                if self._current_file != latest:
                    self._switch_to(latest)

                line = self._fp.readline() if self._fp else ""
                if not line:
                    time.sleep(0.2)
                    continue

                try:
                    evt = json.loads(line)
                    if isinstance(evt, dict):
                        self.event_received.emit(evt)
                except Exception:
                    # Bad line shouldn't crash the app
                    log.exception("Bad JSON line")
                    self.error.emit("Bad journal line (JSON parse failed). Skipped.")

            except Exception:
                log.exception("Watcher loop error")
                self.error.emit("Journal watcher error (see log).")
                time.sleep(1.0)

        self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._fp:
                self._fp.close()
        except Exception:
            pass
        self._fp = None

    def _switch_to(self, path: Path) -> None:
        self._cleanup()
        self._current_file = path
        self._fp = path.open("r", encoding="utf-8", errors="replace")
        self.event_received.emit({"event": "_BootstrapStart"})
        self._bootstrap_newest_system()
        self.event_received.emit({"event": "_BootstrapEnd"})
        self.status.emit(f"Tailing: {path.name}")

    def _is_distance_valid(self, lat: float, lon: float, radius: float) -> bool:
        # Implement distance validation logic here
        return True  # Placeholder for actual validation logic

    def _bootstrap_newest_system(self, max_bytes: int = 256 * 1024, max_events: int = 800) -> None:
        if not self._fp or not self._current_file:
            return
        try:
            size = self._current_file.stat().st_size
            start = max(0, size - max_bytes)
            self._fp.seek(start, 0)
            # If we started mid-line, discard the partial line
            if start > 0:
                self._fp.readline()

            events: List[Dict[str, Any]] = []
            for line in self._fp:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                    if isinstance(evt, dict):
                        events.append(evt)
                        if len(events) >= max_events:
                            break
                except Exception:
                    # Don't spam UI errors during bootstrap
                    log.exception("Bad JSON during bootstrap")
                    continue

            if not events:
                return

            # Find last system anchor in this chunk
            anchor = 0
            for i in range(len(events) - 1, -1, -1):
                name = events[i].get("event")
                if name in ("Location", "FSDJump"):
                    anchor = i
                    break

            emitted = 0
            for evt in events[anchor:]:
                self.event_received.emit(evt)
                emitted += 1

            self.status.emit(f"Bootstrapped {emitted} events (newest system only)")
        except Exception:
            log.exception("Bootstrap failed")

    def _find_latest_journal(self, journal_dir: Path) -> Optional[Path]:
        files: List[Path] = sorted(journal_dir.glob("Journal*.log"))
        if not files:
            return None
        return max(files, key=lambda p: p.stat().st_mtime)
