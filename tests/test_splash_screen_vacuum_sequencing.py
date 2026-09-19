"""SplashScreen's one-time database vacuum step -- confirmed live as two
real bugs:

1. _finish() used to call QTimer.singleShot(200, self._finish) to wait
   for the vacuum step, re-running self._canvas.stop() (which schedules
   its QTimer for deleteLater()) on every retry -- the second call hit
   an already-deleted C++ object and crashed unhandled, leaving the
   splash screen stuck forever, never reaching launch.
2. MainWindow used to be constructed before the vacuum step ran, but
   MainWindow.__init__ starts background threads (EDDN/TTS/EDSM) that
   immediately open their own connections and start writing to the same
   db files -- those writes collided with the vacuum's exclusive lock
   ("database is locked" errors, an 80s EDDN flush stall). MainWindow is
   now only constructed by on_vacuum_done(), strictly after the vacuum
   step returns.

Uses a real QApplication (matches this file's actual thread/QTimer
sequencing being the thing under test -- a fake-self mock would not
exercise the real deleteLater()/QTimer interaction that caused bug #1)."""
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from edc.ui.splash_screen import SplashScreen, BOOT_LINES


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_vacuum_slower_than_boot_animation_still_launches_without_crashing(qapp):
    # Regression for bug #1: vacuum takes longer than the boot animation,
    # so _finish() (scheduled at the animation's end) has to wait -- this
    # must not crash even though the wait spans several retry ticks.
    events = []

    def vacuum_runner(status_callback):
        status_callback("OPTIMIZING TEST DB (ONE-TIME, PLEASE WAIT)...")
        time.sleep(0.5)
        events.append("vacuum_done")

    def on_vacuum_done():
        assert "vacuum_done" in events
        events.append("mainwindow_constructed")

    def import_runner(progress_callback):
        assert "mainwindow_constructed" in events, "import started before MainWindow constructed!"
        progress_callback(1, 1)
        events.append("import_done")

    done = []
    splash = SplashScreen(
        on_done=lambda: done.append(True),
        import_runner=import_runner,
        vacuum_runner=vacuum_runner,
        on_vacuum_done=on_vacuum_done,
    )
    splash.show()
    splash._line_index = len(BOOT_LINES)
    QTimer.singleShot(50, splash._finish)

    deadline = time.monotonic() + 5.0
    while not done and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert events == ["vacuum_done", "mainwindow_constructed", "import_done"]
    assert done, "on_done was never called -- splash got stuck"
    splash.close()


def test_vacuum_already_switched_launches_immediately(qapp):
    # Fast path: auto_vacuum already INCREMENTAL, vacuum_runner returns
    # near-instantly with no status message -- must not block on the
    # boot animation either.
    events = []

    def vacuum_runner(status_callback):
        events.append("vacuum_done")  # no status_callback call -- nothing to show

    def on_vacuum_done():
        events.append("mainwindow_constructed")

    def import_runner(progress_callback):
        events.append("import_done")

    done = []
    splash = SplashScreen(
        on_done=lambda: done.append(True),
        import_runner=import_runner,
        vacuum_runner=vacuum_runner,
        on_vacuum_done=on_vacuum_done,
    )
    splash.show()

    deadline = time.monotonic() + 2.0
    while "import_done" not in events and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    # Import must not wait for the ~8-10s cosmetic boot animation --
    # it starts as soon as vacuum (a no-op here) reports done.
    assert events == ["vacuum_done", "mainwindow_constructed", "import_done"]
    splash.close()


def test_no_vacuum_runner_behaves_like_before_it_existed(qapp):
    events = []

    def on_vacuum_done():
        events.append("mainwindow_constructed")

    def import_runner(progress_callback):
        assert events == ["mainwindow_constructed"]
        events.append("import_done")

    done = []
    splash = SplashScreen(
        on_done=lambda: done.append(True),
        import_runner=import_runner,
        vacuum_runner=None,
        on_vacuum_done=on_vacuum_done,
    )
    splash.show()

    deadline = time.monotonic() + 2.0
    while "import_done" not in events and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert events == ["mainwindow_constructed", "import_done"]
    splash.close()
