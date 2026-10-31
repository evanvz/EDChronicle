"""The UI stall log must name what every other thread is doing and how much CPU the
process used during the stall -- the UI stack alone often just shows app.exec()."""
import gc
import logging
import threading
import time


def test_stall_log_includes_other_threads_and_cpu(caplog):
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QObject
    from edc.ui.main_window import _UiStallWatchdog
    app = QApplication.instance() or QApplication([])
    parent = QObject()
    caplog.set_level(logging.WARNING)
    wd = _UiStallWatchdog(parent)
    app.processEvents()

    stop = threading.Event()

    def busy_worker():
        while not stop.is_set():
            sum(range(10_000))

    worker = threading.Thread(target=busy_worker, name="busy-worker", daemon=True)
    worker.start()
    time.sleep(5.5)  # UI thread blocked: no heartbeat (report at 2 s, re-sample at 4 s+)
    stop.set()
    worker.join()
    app.processEvents()
    time.sleep(0.7)  # let the watchdog see the recovery

    stall = [r.getMessage() for r in caplog.records if "unresponsive" in r.getMessage()]
    assert stall, "no stall logged"
    assert "thread busy-worker" in stall[0] and "busy_worker" in stall[0]
    assert "process CPU" in stall[0]
    again = [r.getMessage() for r in caplog.records if "still stalled" in r.getMessage()]
    assert again and "test_stall_log_includes_other_threads_and_cpu" in again[0]   # the blocked UI frame, re-sampled
    gc.callbacks.remove(wd._gc_timer)
    gc.collect()  # callback removed cleanly; collections still work
    wd._timer.stop()
    wd._beat = float("inf")  # the daemon watchdog outlives the test; stop it reporting


def test_windows_suspending_the_process_is_not_a_stall(caplog):
    """Modern Standby suspends every thread, the watchdog's included; its own sleep
    overrunning means the process was paused, so no stall is reported."""
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QObject
    import edc.ui.main_window as mw
    app = QApplication.instance() or QApplication([])
    caplog.set_level(logging.WARNING)
    real_sleep = time.sleep
    calls = {"n": 0}
    earlier_threads = {t.ident for t in threading.enumerate()}  # e.g. the other test's watchdog

    def fake_sleep(s):
        t = threading.current_thread()
        if t.name == "ui-stall-watchdog" and t.ident not in earlier_threads:
            calls["n"] += 1
            if calls["n"] == 2:  # the whole process "suspended" for 3 s
                real_sleep(3.0)
                return
        real_sleep(s)

    with patch.object(mw.time, "sleep", fake_sleep):
        parent = QObject()
        wd = mw._UiStallWatchdog(parent)
        app.processEvents()
        real_sleep(0.6)      # first normal watchdog tick
        real_sleep(3.0)      # UI thread also "suspended" (no heartbeat) during the pause
        app.processEvents()
        real_sleep(1.2)
    gc.callbacks.remove(wd._gc_timer)
    wd._timer.stop()
    wd._beat = float("inf")
    assert calls["n"] >= 3
    assert not [r for r in caplog.records if "unresponsive" in r.getMessage()]
