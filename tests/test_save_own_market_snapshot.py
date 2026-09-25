"""MainWindow._save_own_market_snapshot() / _MarketSaveWorker -- persists
the player's own just-read Market.json straight into the local
market_prices search table, off the UI thread. Previously this data only
ever refreshed the live UI and (if EDDN contribution happened to be
enabled) got published outward -- the local search index only ever got
filled by EDDN's crowd feed relaying data back, so a commander's own
dock-and-buy never showed up in their own market search until some other
commander (or an EDDN round-trip of their own publish) reported the same
station. Confirmed live 2026-09-25.

A first version of this fix wrote directly on the UI thread and caused a
real freeze-with-no-response while the market window was open (confirmed
live, same day) -- net.market_prices is a multi-million-row table also
written by the EDDN flush worker, so a synchronous write could block on
whatever background writer currently holds the WAL lock. Moved off-thread
via _MarketSaveWorker, same shape as _SpanshSaveWorker
(see test_spansh_save_worker.py, the pattern this file mirrors)."""
from types import SimpleNamespace
from unittest.mock import patch

from edc.ui.main_window import MainWindow, _MarketSaveWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _market(items, station_type="Orbis"):
    return {
        "timestamp": "2026-09-25T10:00:00Z",
        "event": "Market",
        "MarketID": 128049152,
        "StationName": "Jameson Memorial",
        "StationType": station_type,
        "StarSystem": "Shinrarta Dezhra",
        "Items": items,
    }


def _item(name="$platinum_name;", **overrides):
    it = {
        "id": 128049152,
        "Name": name,
        "Name_Localised": "Platinum",
        "Category": "$MARKET_category_metals;",
        "Category_Localised": "Metals",
        "BuyPrice": 0,
        "SellPrice": 59006,
        "MeanPrice": 55505,
        "StockBracket": 0,
        "DemandBracket": 3,
        "Stock": 0,
        "Demand": 33966,
        "Consumer": True,
        "Producer": False,
        "Rare": False,
    }
    it.update(overrides)
    return it


# --- _MarketSaveWorker.run() -- the actual off-thread DB write ---

def test_worker_saves_market_prices_and_commodity_names(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    records = [(
        128049152, "platinum", "Jameson Memorial", "Orbis", "Shinrarta Dezhra",
        59006, 0, 55505, 33966, 3, 0, 0, "2026-09-25T10:00:00Z",
    )]
    name_pairs = [("platinum", "Platinum")]

    worker = _MarketSaveWorker(db_path, records, name_pairs)
    results = []
    worker.finished.connect(lambda: results.append(True))
    worker.run()

    assert results == [True]
    db = Database(db_path)
    try:
        repo = Repository(db)
        rows = db.conn.execute(
            "SELECT commodity_name, station_name FROM net.market_prices WHERE market_id = ?", (128049152,),
        ).fetchall()
        assert [dict(r) for r in rows] == [{"commodity_name": "platinum", "station_name": "Jameson Memorial"}]
        assert repo.get_all_commodity_display_names() == ["Platinum"]
    finally:
        db.close()


def test_worker_with_empty_records_and_pairs_saves_nothing_and_still_emits(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    worker = _MarketSaveWorker(db_path, [], [])
    results = []
    worker.finished.connect(lambda: results.append(True))
    worker.run()  # must not raise

    assert results == [True]


# --- _save_own_market_snapshot() -- builds records and dispatches the worker ---

class _BusyThread:
    def isRunning(self):
        return True


class _TrackedThread:
    """Fake old QThread -- records whether .wait() was called."""
    def __init__(self, calls):
        self._calls = calls

    def isRunning(self):
        return False

    def wait(self):
        self._calls.append("old.wait")


class _FakeNewThread:
    def __init__(self, *a, **kw):
        self.started = self

    def connect(self, *a, **kw):
        pass

    def start(self):
        pass

    def quit(self):
        pass


class _FakeWorker:
    """Captures the constructor args _MarketSaveWorker was built with."""
    last_init_args = None

    def __init__(self, *a, **kw):
        _FakeWorker.last_init_args = a
        self.finished = self

    def moveToThread(self, *a, **kw):
        pass

    def connect(self, *a, **kw):
        pass

    def run(self):
        pass


def _fake_self(name_pairs=None):
    return SimpleNamespace(
        state=SimpleNamespace(current_market_name_pairs=name_pairs),
        repo=SimpleNamespace(db=SimpleNamespace(db_path="unused.db")),
        _market_save_thread=None,
        _market_save_worker=None,
    )


def test_valid_market_dispatches_worker_with_correct_records():
    fake_self = _fake_self(name_pairs=[("platinum", "Platinum")])
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()), \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))
    db_path, records, name_pairs = _FakeWorker.last_init_args
    assert db_path == "unused.db"
    assert records == [(
        128049152, "platinum", "Jameson Memorial", "Orbis", "Shinrarta Dezhra",
        59006, 0, 55505, 33966, 3, 0, 0, "2026-09-25T10:00:00Z",
    )]
    assert name_pairs == [("platinum", "Platinum")]
    assert fake_self._market_save_thread is not None


def test_missing_name_pairs_on_state_defaults_to_empty_list():
    fake_self = _fake_self(name_pairs=None)
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()), \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))
    _db_path, _records, name_pairs = _FakeWorker.last_init_args
    assert name_pairs == []


def test_invalid_market_data_does_not_dispatch_a_worker():
    fake_self = _fake_self()
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()) as mock_thread, \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, {"Items": []})  # missing required fields
    mock_thread.assert_not_called()
    assert fake_self._market_save_thread is None


def test_skipped_while_a_previous_save_is_still_running():
    fake_self = _fake_self()
    fake_self._market_save_thread = _BusyThread()
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()) as mock_thread, \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))
    mock_thread.assert_not_called()
    assert fake_self._market_save_thread is fake_self._market_save_thread  # unchanged, still the busy fake


def test_waits_on_old_thread_before_reassigning():
    calls = []
    old_thread = _TrackedThread(calls)
    fake_self = _fake_self()
    fake_self._market_save_thread = old_thread
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()), \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))
    assert calls == ["old.wait"]
    assert fake_self._market_save_thread is not old_thread


def test_skips_wait_when_no_old_thread():
    fake_self = _fake_self()
    with patch("edc.ui.main_window.QThread", return_value=_FakeNewThread()), \
         patch("edc.ui.main_window._MarketSaveWorker", _FakeWorker):
        MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))  # must not raise
