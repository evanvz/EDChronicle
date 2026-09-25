"""Repository.record_faction_trade_sold / get_faction_trade_sold_since --
persists commodity/exploration/exobiology sale value credited to the
selling station's controlling faction, per system, for the session BGS
activity report. Real SQLite (temp file), matching this repo's
convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_sale(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "commodity", "value": 63085, "sold_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_sales_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-24T10:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_all_three_kinds_tracked(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-25T11:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exobiology", 1804100, "2026-09-25T12:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert {r["kind"] for r in rows} == {"commodity", "exploration", "exobiology"}
