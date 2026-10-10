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
    time.sleep(2.8)  # UI thread blocked: no heartbeat
    stop.set()
    worker.join()
    app.processEvents()
    time.sleep(0.7)  # let the watchdog see the recovery

    stall = [r.getMessage() for r in caplog.records if "unresponsive" in r.getMessage()]
    assert stall, "no stall logged"
    assert "thread busy-worker" in stall[0] and "busy_worker" in stall[0]
    assert "process CPU" in stall[0]
    gc.callbacks.remove(wd._gc_timer)
    gc.collect()  # callback removed cleanly; collections still work
