"""Closing the app must cancel long-running workers and wait for their threads
to actually finish. Confirmed crash 2026-09-27 01:07: the Player Faction
"Full EDSM refresh" was mid-loop at close; shutdown only did quit()+wait(3000)
(quit() doesn't stop a running loop), never called the worker's cancel(), and
the worker's C++ object was deleted while its thread still ran ->
"wrapped C/C++ object of type _FactionRefreshWorker has been deleted"."""
import sys
import time
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from edc.ui.main_window import MainWindow

_app = QApplication.instance() or QApplication(sys.argv)


class _SlowLoopWorker(QObject):
    """Like _FactionRefreshWorker: a loop that only stops when cancelled,
    each iteration longer than the old 3s shutdown wait."""
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._cancel = False
        self.cancelled = False

    def cancel(self):
        self._cancel = True
        self.cancelled = True

    def run(self):
        deadline = time.monotonic() + 30
        while not self._cancel and time.monotonic() < deadline:
            time.sleep(0.05)
        self.finished.emit()


def test_close_cancels_workers_and_waits_for_their_threads():
    worker = _SlowLoopWorker()
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    panel = SimpleNamespace(_refresh_all_thread=thread, _refresh_all_worker=worker)
    thread.start()
    time.sleep(0.2)
    assert thread.isRunning()

    t0 = time.monotonic()
    MainWindow._stop_background_threads(SimpleNamespace(), panel)
    elapsed = time.monotonic() - t0

    assert worker.cancelled
    assert not thread.isRunning()
    assert elapsed < 5
