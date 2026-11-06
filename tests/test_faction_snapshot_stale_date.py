"""An EDSM poll stamps its row with the day of the fetch, not the day of the
reading. A lagging reading must not outrank fresher data just by being dated
later (live case: Delta Indi 70.8% over 75.3%, 2026-11-06)."""
from datetime import date, timedelta

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

DELTA = 2415675804019
EUW = "Elite United Worlds"
TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TODAY = TODAY.isoformat()
OLD_TS, NEW_TS, NEWER_TS = (f"{YESTERDAY}T{t}Z" for t in ("17:29:24", "21:02:41", "23:00:00"))


def _repo(tmp_path):
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    return Repository(db)


def _save(repo, inf, day, ts, source):
    repo.save_faction_snapshot(DELTA, {"Name": EUW, "Influence": inf}, day, True, ts, source)


def _latest(repo):
    return repo.get_faction_history(DELTA, EUW)[0]["influence"]


def test_lagging_reading_on_a_later_date_does_not_outrank_fresher_data(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, 0.753, YESTERDAY, NEW_TS, "hub")
    _save(repo, 0.708, TODAY, OLD_TS, "edsm")
    assert _latest(repo) == 0.753
    assert len(repo.get_faction_history(DELTA, EUW)) == 1


def test_lagging_reading_is_still_kept_as_history(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, 0.753, YESTERDAY, NEW_TS, "hub")
    _save(repo, 0.708, TODAY, OLD_TS, "edsm")
    rows = repo.db.execute("SELECT influence FROM faction_readings WHERE observed_at = ?", (OLD_TS,)).fetchall()
    assert [r[0] for r in rows] == [0.708]


def test_fresher_reading_on_a_later_date_is_saved(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, 0.753, YESTERDAY, NEW_TS, "hub")
    _save(repo, 0.76, TODAY, NEWER_TS, "hub")
    assert _latest(repo) == 0.76


def test_same_reading_on_a_later_date_is_saved(tmp_path):
    # quiet system: the daily refresh re-dates an unchanged reading, keeping it inside retention
    repo = _repo(tmp_path)
    _save(repo, 0.753, YESTERDAY, NEW_TS, "hub")
    _save(repo, 0.753, TODAY, NEW_TS, "hub")
    assert len(repo.get_faction_history(DELTA, EUW)) == 2


def test_older_backfill_on_an_earlier_date_is_saved(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, 0.753, TODAY, f"{TODAY}T10:00:00Z", "journal")
    _save(repo, 0.60, YESTERDAY, NEW_TS, "journal")
    assert len(repo.get_faction_history(DELTA, EUW)) == 2


def test_no_timestamp_is_saved(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, 0.753, YESTERDAY, NEW_TS, "hub")
    _save(repo, 0.70, TODAY, None, "csv")
    assert _latest(repo) == 0.70
