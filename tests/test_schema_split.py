"""Confirms CACHE_SCHEMA_SQL creates its 4 tables in the attached `net`
schema, not `main` -- the whole split depends on this being right, since
an unqualified CREATE TABLE in a script run against a connection with
`net` attached still lands in `main` by default."""
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
