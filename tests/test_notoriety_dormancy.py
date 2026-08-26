"""Notoriety estimation + bounty dormancy tracking."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine():
    e = EventEngine.__new__(EventEngine)
    e.state = GameState()
    return e


def _evt(**kw):
    return {"event": "CommitCrime", "timestamp": "2026-08-26T12:00:00Z", **kw}


def test_onfoot_murder_increments_pending_notoriety():
    e = _engine()
    e.process(_evt(CrimeType="onFoot_murder", Faction="F", Bounty=1000))
    assert e.state.notoriety_est_pending_murders == 1


def test_ship_murder_increments_pending_notoriety():
    e = _engine()
    e.process(_evt(CrimeType="murder", Faction="F", Bounty=1000))
    assert e.state.notoriety_est_pending_murders == 1


def test_statistics_resets_pending():
    e = _engine()
    e.process(_evt(CrimeType="onFoot_murder", Faction="F", Bounty=1000))
    e.process({"event": "Statistics", "timestamp": "2026-08-26T12:00:00Z",
               "Crime": {"Notoriety": 0}})
    assert e.state.notoriety == 0
    assert e.state.notoriety_est_pending_murders == 0


def test_bounty_last_commit_recorded_and_cleared():
    e = _engine()
    e.process(_evt(CrimeType="assault", Faction="F", Bounty=1000))
    assert e.state.bounty_last_commit == {"F": "2026-08-26T12:00:00Z"}
    e.process({"event": "PayBounties", "timestamp": "2026-08-26T13:00:00Z", "Faction": "F"})
    assert e.state.bounty_last_commit == {}


def test_nonmurder_crime_no_notoriety_estimate():
    e = _engine()
    e.process(_evt(CrimeType="assault", Faction="F", Bounty=1000))
    assert e.state.notoriety_est_pending_murders == 0
