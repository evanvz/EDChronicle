"""Database.deferred_commit() -- suppresses execute()'s per-call
auto-commit for a block, doing one commit at the end instead. Confirmed
live: EDDN flush loops (factions/bgs_status/etc, up to ~400 items per
45s tick) were driving a ~30s WAL checkpoint stall by committing --
and fsyncing -- once per item instead of once per flush."""
import sqlite3

import pytest

from persistence.database import Database


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    db.conn.commit()
    return db


def test_execute_commits_immediately_by_default(db):
    db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
    other = sqlite3.connect(db.db_path)
    assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    other.close()


def test_deferred_commit_holds_writes_until_block_exits(db):
    other = sqlite3.connect(db.db_path)
    with db.deferred_commit():
        db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
        db.execute("INSERT INTO t (val) VALUES (?)", ("b",))
        # Not visible to another connection yet -- no commit happened.
        assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    other.close()


def test_nested_deferred_commit_is_reentrant_safe(db):
    other = sqlite3.connect(db.db_path)
    with db.deferred_commit():
        db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
        with db.deferred_commit():
            db.execute("INSERT INTO t (val) VALUES (?)", ("b",))
        # Inner exit must not have committed -- outer block still open.
        assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    other.close()


def test_execute_still_commits_immediately_after_deferred_block_ends(db):
    with db.deferred_commit():
        db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
    other = sqlite3.connect(db.db_path)
    db.execute("INSERT INTO t (val) VALUES (?)", ("b",))
    assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    other.close()
