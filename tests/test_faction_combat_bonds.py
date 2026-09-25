"""Repository.record_faction_combat_bond / get_faction_combat_bonds_since
-- persists FactionKillBond rewards per system+faction for the new
session BGS activity report. Bounty vouchers are deliberately excluded
(the journal's Bounty event carries VictimFaction, not which faction
actually credits the voucher -- that's determined later, at redemption).
Real SQLite (temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_bond(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "reward": 15000, "earned_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_bonds_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-24T10:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_multiple_bonds_accumulate(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 5000, "2026-09-25T11:00:00Z")
    repo.record_faction_combat_bond(999, "Hungarian Wolves", 8000, "2026-09-25T12:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert len(rows) == 3
    assert sum(r["reward"] for r in rows) == 28000
