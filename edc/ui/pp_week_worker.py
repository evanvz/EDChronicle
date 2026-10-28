# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
"""Background fetch of PowerPlay readings from EDDataHub for the Watch List.
Hub readings are only cached in memory, never written to SQLite."""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

from edc.core.eddatahub_client import fetch_system_powerplay

log = logging.getLogger(__name__)

_CACHE: dict = {}      # id64 -> (fetched_monotonic, since, readings)
_MAX_AGE_S = 600


class _Worker(QObject):
    finished = pyqtSignal(object)   # Optional[dict]

    def __init__(self, hub_url: str, ids: list, since: str):
        super().__init__()
        self._hub_url, self._ids, self._since = hub_url, ids, since

    def run(self):
        data = None
        try:
            data = fetch_system_powerplay(self._hub_url, self._ids, self._since)
        except Exception:
            log.exception("EDDataHub PowerPlay fetch failed")
        self.finished.emit(data)


class HubPowerplayFetch(QObject):
    done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    def start(self, hub_url: str, ids: list, since: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        now = time.monotonic()
        if all(i in _CACHE and now - _CACHE[i][0] < _MAX_AGE_S and _CACHE[i][1] == since for i in ids):
            self.done.emit({i: _CACHE[i][2] for i in ids})
            return
        if not hub_url:
            self.done.emit({})
            return
        self._since = since
        self._worker = _Worker(hub_url, list(ids), since)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, data) -> None:
        if not data:
            self.done.emit({})
            return
        now = time.monotonic()
        for i, readings in data.items():
            _CACHE[i] = (now, self._since, readings)
        self.done.emit(data)
