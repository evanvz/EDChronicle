"""_SearchIndexWorker -- one-shot background build of market_prices/
system_coords search indexes (previously only ever built via Settings'
manual "Compact Database Now" button, so most installs ran every search
against an unindexed table indefinitely). Also covers
AppConfig.search_indexes_ensured's save/load round trip, the flag that
skips even the no-op CREATE INDEX IF NOT EXISTS check on future startups
once confirmed done."""
from edc.config import AppConfig, ConfigStore
from edc.ui.main_window import _SearchIndexWorker
from persistence.database import Database
from persistence.schema import SCHEMA_SQL


def test_worker_creates_both_indexes(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    worker = _SearchIndexWorker(db_path)
    results = []
    worker.finished.connect(lambda: results.append(True))
    worker.run()

    assert results == [True]
    db = Database(db_path)
    try:
        market_idx = db.conn.execute(
            "SELECT name FROM net.sqlite_master WHERE type='index' AND name='idx_market_prices_system_name'"
        ).fetchall()
        coords_idx = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_system_coords_xyz'"
        ).fetchall()
        assert len(market_idx) == 1
        assert len(coords_idx) == 1
    finally:
        db.close()


def test_worker_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    _SearchIndexWorker(db_path).run()
    _SearchIndexWorker(db_path).run()  # must not raise on a second run


def test_search_indexes_ensured_round_trips(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = AppConfig(search_indexes_ensured=True)
    store.save(cfg)

    loaded = store.load()
    assert loaded.search_indexes_ensured is True


def test_search_indexes_ensured_defaults_false():
    assert AppConfig().search_indexes_ensured is False
