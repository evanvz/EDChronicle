"""_data_age_days() and the "Stale Data (>7d)" bucket it feeds -- must use
data_timestamp (the source's real last-update time), not snapshot_date
(the date WE last wrote a row, re-stamped "today" on every poll even
when EDSM's underlying data hasn't changed). Confirmed live: a real
system had data_timestamp frozen at one date for 5+ days while
snapshot_date ticked forward daily -- a snapshot_date-based check could
never flag it as stale under normal daily polling, no matter how old
the real data actually was."""
from datetime import date, timedelta

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.ui.panels.player_faction_panel import _data_age_days


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _faction(name="Our Faction", influence=0.5):
    return {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}


# --- _data_age_days() ---

def test_age_computed_from_data_timestamp_not_snapshot_date():
    today = date(2026, 9, 3)
    sys_rec = {"snapshot_date": "2026-09-03", "data_timestamp": "2026-08-30T15:20:00Z"}
    assert _data_age_days(sys_rec, today) == 4


def test_frozen_data_timestamp_across_daily_snapshot_reads_stays_stale():
    # The exact real-world case: snapshot_date advances every day (we
    # keep polling) but data_timestamp never moves (EDSM never refreshed
    # it) -- age must track data_timestamp, not go back to 0 each poll.
    today = date(2026, 9, 3)
    for snapshot_date in ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"):
        sys_rec = {"snapshot_date": snapshot_date, "data_timestamp": "2026-08-30T15:20:00Z"}
        assert _data_age_days(sys_rec, today) == 4


def test_falls_back_to_snapshot_date_when_data_timestamp_absent():
    today = date(2026, 9, 3)
    sys_rec = {"snapshot_date": "2026-08-27"}
    assert _data_age_days(sys_rec, today) == 7


def test_missing_both_fields_returns_none():
    assert _data_age_days({}) is None


def test_unparseable_data_timestamp_returns_none():
    assert _data_age_days({"data_timestamp": "not a date"}) is None


# --- get_player_faction_overview()/get_player_faction_system_status() now expose data_timestamp ---

def test_overview_exposes_data_timestamp(tmp_path):
    repo = _repo(tmp_path)
    f = _faction()
    f["SquadronFaction"] = True
    repo.save_faction_snapshot(1, f, "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm")

    overview = repo.get_player_faction_overview()
    sys_row = overview["systems"][0]
    assert sys_row["data_timestamp"] == "2026-08-30T15:20:00Z"
    assert _data_age_days(sys_row, date(2026, 9, 3)) == 4


def test_system_status_exposes_data_timestamp(tmp_path):
    repo = _repo(tmp_path)
    f = _faction()
    f["SquadronFaction"] = True
    repo.save_faction_snapshot(1, f, "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm")

    result = repo.get_player_faction_system_status("Our Faction", 1)
    assert result["data_timestamp"] == "2026-08-30T15:20:00Z"
