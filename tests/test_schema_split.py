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
