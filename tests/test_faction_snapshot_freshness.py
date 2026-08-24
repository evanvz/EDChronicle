"""Tests for save_faction_snapshot()'s freshness-guarded upsert and its
_normalize_data_timestamp() helper -- real SQLite (temp file), not mocks,
since the guard lives in the SQL itself."""
import pytest

from persistence.database import Database
from persistence.repository import Repository, _normalize_data_timestamp
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _faction(name="Test Faction", influence=0.5):
    return {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}


def _read_row(repo, system_address, faction_name, snapshot_date):
    row = repo.db.conn.execute(
        "SELECT * FROM faction_snapshots WHERE system_address = ? AND faction_name = ? AND snapshot_date = ?",
        (system_address, faction_name, snapshot_date),
    ).fetchone()
    return dict(row) if row else None


# --- _normalize_data_timestamp() ---

def test_normalize_handles_z_suffix_string():
    assert _normalize_data_timestamp("2026-08-12T09:18:35Z") == "2026-08-12T09:18:35Z"


def test_normalize_handles_offset_suffix_string():
    assert _normalize_data_timestamp("2026-08-12T09:18:35+00:00") == "2026-08-12T09:18:35Z"


def test_normalize_handles_unix_epoch():
    # 1786547694 -- confirmed live from a real EDSM lastUpdate value this session;
    # expected value independently verified via datetime.fromtimestamp(1786547694, tz=timezone.utc)
    assert _normalize_data_timestamp(1786547694) == "2026-08-12T15:14:54Z"


def test_normalize_z_and_epoch_agree_for_the_same_instant():
    epoch = 1786547694
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _normalize_data_timestamp(epoch) == _normalize_data_timestamp(iso)


def test_normalize_falls_back_to_now_for_missing_value():
    from datetime import datetime, timezone
    before = datetime.now(timezone.utc)
    result = _normalize_data_timestamp(None)
    after = datetime.now(timezone.utc)
    # Just confirm it's a valid, well-formed recent timestamp, not a crash.
    parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= parsed <= after or (after - parsed).total_seconds() < 2


# --- save_faction_snapshot()'s freshness guard ---

def test_fresher_write_overwrites_older_row(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    repo.save_faction_snapshot(1, _faction(influence=0.7), "2026-08-12", False, "2026-08-12T12:00:00Z", "eddn")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.7
    assert row["source"] == "eddn"
    assert row["data_timestamp"] == "2026-08-12T12:00:00Z"


def test_staler_write_does_not_overwrite_newer_row(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.7), "2026-08-12", False, "2026-08-12T12:00:00Z", "eddn")
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.7  # unchanged -- the older write was rejected
    assert row["source"] == "eddn"


def test_equal_timestamp_write_does_overwrite(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    repo.save_faction_snapshot(1, _faction(influence=0.4), "2026-08-12", False, "2026-08-12T09:00:00Z", "journal")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.4


def test_any_write_overwrites_a_legacy_null_timestamp_row(repo):
    # Simulate a pre-migration row: insert directly, bypassing the
    # timestamp-aware method entirely, leaving data_timestamp NULL.
    repo.db.conn.execute(
        """INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date, influence, is_controlling)
           VALUES (?, ?, ?, ?, ?)""",
        (1, "Test Faction", "2026-08-12", 0.1, 0),
    )
    repo.db.conn.commit()
    repo.save_faction_snapshot(1, _faction(influence=0.9), "2026-08-12", False, "2026-08-12T01:00:00Z", "edsm")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.9
    assert row["data_timestamp"] == "2026-08-12T01:00:00Z"


def test_source_and_data_timestamp_are_stored_on_first_write(repo):
    repo.save_faction_snapshot(1, _faction(), "2026-08-12", True, "2026-08-12T09:18:35Z", "csv")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["source"] == "csv"
    assert row["data_timestamp"] == "2026-08-12T09:18:35Z"
    assert row["is_controlling"] == 1


# --- get_player_faction_overview()'s same-day tiebreak ---

def test_get_player_faction_overview_breaks_same_day_tie_by_data_timestamp():
    """Regression test: a manually-set placeholder (system_address=0) and
    a real same-day journal detection can tie on snapshot_date alone --
    confirmed live, a manual entry typed in different case than the
    game's own exact string ('ELITE UNITED WORLDS' vs 'Elite United
    Worlds') won that tie non-deterministically before data_timestamp was
    added as a tiebreaker, silently breaking every downstream
    case-sensitive comparison against the real journal Factions[] name."""
    db = Database(":memory:")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    repo.set_manual_squadron_faction("ELITE UNITED WORLDS")
    # Real detection lands later the same day, with the game's own casing.
    repo.save_faction_snapshot(
        3205949786483,
        {"Name": "Elite United Worlds", "SquadronFaction": True, "Influence": 0.4},
        snapshot_date=repo.db.conn.execute("SELECT date('now')").fetchone()[0],
        is_controlling=False,
        data_timestamp="2099-01-01T23:59:59Z",  # later than set_manual_squadron_faction's "now"
        source="journal",
    )
    overview = repo.get_player_faction_overview()
    assert overview["faction_name"] == "Elite United Worlds"
