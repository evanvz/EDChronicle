import logging
from PyQt6.QtCore import QThread
from edc.core.journal_watcher import JournalWatcher
from edc.core.status_watcher import StatusWatcher

logger = logging.getLogger(__name__)


class WatcherController:

    def __init__(self, on_event, on_status, on_error):
        self._on_event = on_event
        self._on_status = on_status
        self._on_error = on_error

        self.thread = None
        self.watcher = None
        self.status_thread = None
        self.status_watcher = None

    def start_watching(self, journal_path, status_path):
        logger.info("WatcherController: starting watchers")

        self.thread = QThread()
        self.watcher = JournalWatcher(journal_path)
        self.watcher.moveToThread(self.thread)
        self.thread.started.connect(self.watcher.run)
        self.watcher.status.connect(self._on_status)
        self.watcher.error.connect(self._on_error)
        self.watcher.event_received.connect(self._on_event)
        self.thread.start()

        self.status_thread = QThread()
        self.status_watcher = StatusWatcher(status_path)
        self.status_watcher.moveToThread(self.status_thread)
        self.status_thread.started.connect(self.status_watcher.run)
        self.status_watcher.error.connect(self._on_error)
        self.status_watcher.event_received.connect(self._on_event)
        self.status_thread.start()

        logger.info("WatcherController: watchers started")

    def stop_watching(self):
        logger.info("WatcherController: stopping watchers")

        if self.watcher:
            self.watcher.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(1500)

        if self.status_watcher:
            self.status_watcher.stop()
        if self.status_thread:
            self.status_thread.quit()
            self.status_thread.wait(1500)

        self.thread = None
        self.watcher = None
        self.status_thread = None
        self.status_watcher = None

        logger.info("WatcherController: watchers stopped")
