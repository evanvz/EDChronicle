import sqlite3
import threading
import time

from persistence.database import Database, interrupt_reads

_SLOW = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 300000000) "


def _run_in_thread(path, sql, ready):
    out = {}

    def go():
        db = Database(path)  # own connection per thread, like the app's workers
        db.conn.execute("CREATE TABLE IF NOT EXISTS t (i INTEGER)")
        db.conn.commit()
        ready.set()
        t0 = time.monotonic()
        try:
            db.conn.execute(sql)
            out["result"] = "finished"
        except sqlite3.OperationalError as e:
            out["result"] = str(e)
        out["secs"] = time.monotonic() - t0
        db.conn.rollback()
    th = threading.Thread(target=go)
    th.start()
    return th, out


def test_close_interrupts_a_running_read(tmp_path):
    ready = threading.Event()
    th, out = _run_in_thread(tmp_path / "a.db", _SLOW + "SELECT count(*) FROM n", ready)
    ready.wait(5)
    time.sleep(0.3)
    interrupt_reads()
    th.join(10)
    assert out["result"] == "interrupted" and out["secs"] < 5


def test_close_leaves_a_running_write_alone(tmp_path):
    ready = threading.Event()
    # starts with INSERT, as the app's writes do: that is what opens sqlite3's implicit transaction
    sql = "INSERT INTO t SELECT i FROM (" + _SLOW.replace("300000000", "3000000") + "SELECT i FROM n)"
    th, out = _run_in_thread(tmp_path / "b.db", sql, ready)
    ready.wait(5)
    time.sleep(0.1)
    interrupt_reads()
    th.join(60)
    assert out["result"] == "finished"
