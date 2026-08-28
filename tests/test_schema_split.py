"""Confirms CACHE_SCHEMA_SQL creates its 4 tables in the attached `net`
schema, not `main` -- the whole split depends on this being right, since
an unqualified CREATE TABLE in a script run against a connection with
`net` attached still lands in `main` by default."""
from pathlib import Path

from persistence.database import Database
from persistence.schema import SCHEMA_SQL, CACHE_SCHEMA_SQL


def test_cache_schema_sql_creates_tables_in_net_schema(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)

    net_tables = {
        r[0] for r in db.conn.execute(
            "SELECT name FROM net.sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"spansh_bodies", "station_info", "commodity_names", "market_prices"} <= net_tables

    main_tables = {
        r[0] for r in db.conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "spansh_bodies" not in main_tables
    assert "station_info" not in main_tables
    assert "commodity_names" not in main_tables
    assert "market_prices" not in main_tables
    assert "systems" in main_tables  # sanity: personal tables still in main


def test_cache_db_path_is_a_sibling_file(tmp_path):
    db = Database(tmp_path / "edhelper.db")
    assert db.cache_db_path == tmp_path / "network_cache.db"
    db.close()


def test_memory_mode_attaches_a_private_memory_cache():
    db = Database(":memory:")
    db.executescript(SCHEMA_SQL)
    # CACHE_SCHEMA_SQL is run automatically in __init__, so net schema is
    # populated. This test confirms `net` is attached and queryable in
    # memory mode, with all cache tables present.
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM net.sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"spansh_bodies", "station_info", "commodity_names", "market_prices"} <= tables
    db.close()


def test_corrupted_cache_file_self_heals(tmp_path):
    """A cache file that exists but isn't a valid SQLite database must not
    crash the app -- cache data is disposable by design."""
    cache_path = tmp_path / "network_cache.db"
    cache_path.write_bytes(b"not a real sqlite file")

    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)  # must not raise
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM net.sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "spansh_bodies" in tables
    db.close()


def test_run_migrations_adds_columns_to_both_schemas(tmp_path):
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()

    # A personal-schema migration column (main.bodies)
    body_cols = {r[1] for r in db.conn.execute("PRAGMA main.table_info(bodies)").fetchall()}
    assert "mass_em" in body_cols

    # A cache-schema migration column (net.spansh_bodies)
    spansh_cols = {r[1] for r in db.conn.execute("PRAGMA net.table_info(spansh_bodies)").fetchall()}
    assert "was_mapped" in spansh_cols
    assert "updated_at" in spansh_cols

    # Cache-only tables created purely by migrations (no base CREATE in
    # CACHE_SCHEMA_SQL), e.g. fleet_carrier_materials
    net_tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM net.sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"fleet_carrier_materials", "codex_species_sightings",
            "system_bgs_status", "system_res_sites"} <= net_tables
    db.close()


def test_run_migrations_drops_old_cache_tables_from_personal_db(tmp_path):
    """Defends an existing un-wiped edhelper.db from the pre-split schema
    -- these 8 tables must not linger in main once migrations have run,
    even though nothing writes to them there any more."""
    db_path = tmp_path / "edhelper.db"
    db = Database(db_path)
    db.executescript(SCHEMA_SQL)
    # Simulate a pre-split DB: create market_prices directly in main.
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS market_prices (market_id INTEGER, commodity_name TEXT)"
    )
    db.run_migrations()

    main_tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM main.sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "market_prices" not in main_tables
    db.close()


def test_enable_incremental_auto_vacuum_targets_requested_schema(tmp_path):
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()

    db.enable_incremental_auto_vacuum(schema="net")
    mode = db.conn.execute("PRAGMA net.auto_vacuum").fetchone()[0]
    assert mode == 2  # INCREMENTAL
    # main is untouched by that call -- a schema="net" call must not also
    # flip main's auto_vacuum mode. tmp_path is a fresh file per test, so
    # main starts at the SQLite default (0/NONE), never having been VACUUMed.
    main_mode = db.conn.execute("PRAGMA main.auto_vacuum").fetchone()[0]
    assert main_mode != 2  # NOT INCREMENTAL -- only net was touched
    db.close()


def test_ensure_market_prices_indexes_targets_net_schema(tmp_path):
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()

    db.ensure_market_prices_indexes()
    # Verify the index exists in the net schema by checking PRAGMA net.index_list
    indexes = {r[1] for r in db.conn.execute("PRAGMA net.index_list(market_prices)").fetchall()}
    assert "idx_market_prices_system_name" in indexes

    # Further verify the index actually works by testing a query with the index column.
    # Insert a test row to demonstrate the index can be used.
    db.conn.execute(
        "INSERT INTO net.market_prices (market_id, commodity_name, system_name, sell_price, demand, stock, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "test_commodity", "test_system", 100, 5, 10, "2026-08-28")
    )
    db.conn.commit()
    # Query using the indexed column and verify the query executes without error
    result = db.conn.execute(
        "SELECT * FROM net.market_prices WHERE system_name = ?", ("test_system",)
    ).fetchall()
    assert len(result) == 1
    db.close()


def test_net_schema_is_wal_mode(tmp_path):
    """The whole point of attaching the cache DB as its own file is an
    independent WAL/lock from `main` (see the __init__ comment) -- if
    `net` were left in the default rollback-journal mode, a writer there
    would still take an exclusive lock on the whole cache file, which is
    exactly the contention this split exists to remove."""
    db = Database(tmp_path / "edhelper.db")
    net_mode = db.conn.execute("PRAGMA net.journal_mode").fetchone()[0]
    assert net_mode.lower() == "wal"
    db.close()


def test_net_wal_checkpoint_reports_checkpointed_frames(tmp_path):
    """Guards the exact Finding-1 regression: if `net` isn't actually in
    WAL mode, PRAGMA net.wal_checkpoint(TRUNCATE) silently no-ops and
    reports (0, -1, -1) instead of raising -- so only a real write +
    checkpoint proves it's working, not just checking journal_mode.

    Note: on a *successful* TRUNCATE checkpoint the reported log/
    checkpointed frame counts are 0, not some positive number -- TRUNCATE
    fully drains the WAL and then truncates it to 0 bytes, and the counts
    reflect the WAL's state after that (confirmed empirically: PRAGMA
    net.wal_checkpoint(FULL), which checkpoints but doesn't truncate,
    reports the real pre-checkpoint frame count on this same data). -1 is
    SQLite's actual "nothing to checkpoint / not in WAL mode" signal, so
    that -- plus the WAL sidecar file actually shrinking to 0 bytes -- is
    what this test checks for."""
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.conn.execute(
        "INSERT INTO net.market_prices (market_id, commodity_name, system_name, sell_price, demand, stock, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "test_commodity", "test_system", 100, 5, 10, "2026-08-28"),
    )
    db.conn.commit()

    wal_path = Path(f"{db.cache_db_path}-wal")
    assert wal_path.exists() and wal_path.stat().st_size > 0  # real, unflushed WAL data

    busy, log_frames, checkpointed_frames = db.conn.execute(
        "PRAGMA net.wal_checkpoint(TRUNCATE)"
    ).fetchone()
    assert (log_frames, checkpointed_frames) != (-1, -1)  # -1,-1 == silent no-op (the bug)
    assert wal_path.stat().st_size == 0  # WAL was actually drained and truncated
    db.close()


def test_run_migrations_creates_net_cache_indexes(tmp_path):
    """Verify that run_migrations() actually creates the cache schema indexes
    (idx_fcm_symbol and idx_market_prices_commodity) in the net schema.
    These were silently failing due to incorrect SQL syntax until fixed."""
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()

    # Verify idx_fcm_symbol is created in net.fleet_carrier_materials
    fcm_indexes = {r[1] for r in db.conn.execute("PRAGMA net.index_list(fleet_carrier_materials)").fetchall()}
    assert "idx_fcm_symbol" in fcm_indexes, f"idx_fcm_symbol not found in fleet_carrier_materials indexes: {fcm_indexes}"

    # Verify idx_market_prices_commodity is created in net.market_prices
    mp_indexes = {r[1] for r in db.conn.execute("PRAGMA net.index_list(market_prices)").fetchall()}
    assert "idx_market_prices_commodity" in mp_indexes, f"idx_market_prices_commodity not found in market_prices indexes: {mp_indexes}"

    db.close()
