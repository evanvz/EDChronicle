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
