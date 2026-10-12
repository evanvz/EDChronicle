"""2026-10-12 live freeze: the Market panel's Spansh power-lookup finish handler
re-rendered, which started a new lookup, which called old_thread.wait() on the
UI thread -- but the old thread's quit() was a queued call behind that very
handler, so wait() never returned (UI hung forever, process CPU 0). Connecting
worker.finished -> thread.quit with DirectConnection runs quit() on the worker
thread at emit time, so the old thread is already stopping when any handler runs."""
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT = r'''
import sys
from PyQt6.QtCore import QCoreApplication, QObject, QThread, QTimer, Qt, pyqtSignal

app = QCoreApplication([])
mode = sys.argv[1]

class Worker(QObject):
    finished = pyqtSignal()
    def run(self):
        self.finished.emit()

class Owner(QObject):
    def __init__(self):
        super().__init__()
        self.thread, self.runs = None, 0
    def start(self):
        if self.thread is not None:
            self.thread.wait()          # the old-thread teardown wait used across the app
        self.thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_finished)
        if mode == "direct":
            self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        else:
            self.worker.finished.connect(self.thread.quit)
        self.thread.start()
    def on_finished(self):
        self.runs += 1
        if self.runs < 3:
            self.start()                # restart from inside the finish handler
        else:
            self.thread.wait()
            print("done", self.runs)
            app.quit()

o = Owner()
QTimer.singleShot(0, o.start)
app.exec()
'''


def _run(mode: str):
    return subprocess.run([sys.executable, "-c", _SCRIPT, mode], capture_output=True, text=True, timeout=6)


def test_restart_from_finish_handler_does_not_deadlock():
    assert _run("direct").stdout.strip() == "done 3"


def test_queued_quit_deadlocks_as_seen_live():
    try:
        _run("queued")
    except subprocess.TimeoutExpired:
        return  # the original bug: wait() never returns
    raise AssertionError("expected the queued-quit pattern to deadlock")


def test_every_quit_hookup_in_the_app_is_direct():
    src = Path(__file__).resolve().parents[1] / "edc"
    queued = [f"{p}:{i}" for p in src.rglob("*.py")
              for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
              if re.search(r"\.finished\.connect\([^)]*\.quit\)", line)]
    assert not queued, queued
