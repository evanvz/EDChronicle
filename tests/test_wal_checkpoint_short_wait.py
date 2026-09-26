"""_WalCheckpointWorker must not hold writers off for its full busy_timeout.
A TRUNCATE checkpoint waiting on an active reader blocks every writer to that
database while it waits (verified with a probe script 2026-09-26); with the
app's 30s busy_timeout that stalled the main database for ~32s during a
Market search. The checkpoint connection now gives up after a short wait and
the next 5-minute tick retries."""
import logging
import sqlite3
import time

from edc.ui.main_window import _WalCheckpointWorker
from persistence.database import Database
from persistence.schema import SCHEMA_SQL


def test_checkpoint_gives_up_quickly_when_a_reader_is_active(tmp_path, caplog):
    path = tmp_path / "test.db"
    db = Database(path)
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Ekono')")
    # db stays open (as the app's own connection does) -- closing the last
    # connection would checkpoint the WAL away and leave nothing to wait on.

    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM systems").fetchone()  # holds a read snapshot on main
    db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'Aiga')")  # newer WAL frames
    try:
        caplog.set_level(logging.INFO, logger="edc.ui.main")
        t0 = time.perf_counter()
        _WalCheckpointWorker(path).run()
        elapsed = time.perf_counter() - t0
    finally:
        reader.execute("COMMIT")
        reader.close()
        db.close()

    assert elapsed < 8  # was ~30s per database with the default busy_timeout
    assert "readers still active" in caplog.text
