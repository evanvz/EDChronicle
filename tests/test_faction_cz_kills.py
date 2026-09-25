"""Repository.record_faction_cz_kill / get_faction_cz_kills_since --
persists conflict-zone kill credits (ground/space, small/medium/high)
per system+faction for the session BGS activity report. Real SQLite
(temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_kill(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T10:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "zone_type": "space", "size": "h", "earned_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_kills_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "m", "2026-09-24T10:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_ground_and_space_kills_both_tracked(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "l", "2026-09-25T10:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T11:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert {(r["zone_type"], r["size"]) for r in rows} == {("ground", "l"), ("space", "h")}
