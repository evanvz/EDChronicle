"""_retry_once_if_locked() -- background save workers retry a write once
after "database is locked" instead of dropping it. Confirmed live
2026-09-25: _MarketSaveWorker lost a save to a 30s WAL checkpoint."""
import sqlite3
from types import SimpleNamespace

import pytest

from edc.ui.main_window import _retry_once_if_locked


def _fake_db():
    rollbacks = []
    return SimpleNamespace(conn=SimpleNamespace(rollback=lambda: rollbacks.append(1))), rollbacks


def test_retries_once_after_lock_and_rolls_back_first():
    db, rollbacks = _fake_db()
    calls = []

    def work():
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")

    _retry_once_if_locked(db, work, "test save")
    assert len(calls) == 2
    assert rollbacks == [1]


def test_second_lock_propagates():
    db, _ = _fake_db()

    def work():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        _retry_once_if_locked(db, work, "test save")


def test_other_operational_errors_are_not_retried():
    db, rollbacks = _fake_db()
    calls = []

    def work():
        calls.append(1)
        raise sqlite3.OperationalError("no such table: foo")

    with pytest.raises(sqlite3.OperationalError):
        _retry_once_if_locked(db, work, "test save")
    assert len(calls) == 1
    assert rollbacks == []


def test_success_runs_once():
    db, rollbacks = _fake_db()
    calls = []
    _retry_once_if_locked(db, lambda: calls.append(1), "test save")
    assert calls == [1]
    assert rollbacks == []
