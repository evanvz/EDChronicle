"""Leaving a squadron or PowerPlay pledge mid-life: the app must stop
using the old squadron faction / power."""
from datetime import datetime, timedelta, timezone

from edc.core.event_engine import EventEngine
from edc.core.squadron_events import membership_since
from edc.core.state import GameState
from persistence import repository as R
from persistence.database import Database
from persistence.schema import SCHEMA_SQL


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_powerplay_leave_clears_the_pledge(tmp_path):
    eng = _engine(tmp_path)
    eng.process({"event": "Powerplay", "timestamp": "2026-10-02T10:00:00Z", "Power": "Aisling Duval",
                 "Rank": 50, "Merits": 1000, "TimePledged": 1})
    state, msgs = eng.process({"event": "PowerplayLeave", "timestamp": "2026-10-02T11:00:00Z",
                               "Power": "Aisling Duval"})
    assert state.pp_power is None and state.pp_merits is None
    assert "refresh_powerplay" in msgs


def test_powerplay_defect_and_join_switch_the_pledge(tmp_path):
    eng = _engine(tmp_path)
    state, _ = eng.process({"event": "PowerplayDefect", "timestamp": "2026-10-02T11:00:00Z",
                            "FromPower": "Aisling Duval", "ToPower": "Zemina Torval"})
    assert state.pp_power == "Zemina Torval"
    state, _ = eng.process({"event": "PowerplayJoin", "timestamp": "2026-10-02T12:00:00Z", "Power": "Li Yong-Rui"})
    assert state.pp_power == "Li Yong-Rui"


def test_membership_since_only_for_membership_events():
    assert membership_since("LeftSquadron", "2026-10-02T10:00:00Z") == "2026-10-02T10:00:00Z"
    assert membership_since("JoinedSquadron", "2026-08-01T18:18:53Z") == "2026-08-01T18:18:53Z"
    assert membership_since(None, None) is None


def test_squadron_faction_from_before_leaving_is_ignored(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = R.Repository(db)
    # Relative dates: snapshots older than 30 days are deleted on save.
    flagged = datetime.now(timezone.utc) - timedelta(days=3)
    left = flagged + timedelta(days=1)
    repo.save_faction_snapshot(1, {"Name": "Elite United Worlds", "Influence": 0.6, "SquadronFaction": True},
                               flagged.strftime("%Y-%m-%d"), is_controlling=True,
                               data_timestamp=flagged.strftime("%Y-%m-%dT%H:%M:%SZ"), source="journal")
    try:
        R.set_squadron_membership_since(None)
        assert repo.get_squadron_faction_name() == "Elite United Worlds"
        R.set_squadron_membership_since(left.strftime("%Y-%m-%dT%H:%M:%SZ"))  # left after that flag
        assert repo.get_squadron_faction_name() is None
        assert repo.get_player_faction_overview() is None
    finally:
        R.set_squadron_membership_since(None)
