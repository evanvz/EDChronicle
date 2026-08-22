"""Fines (CommitCrime with a Fine field, cleared by PayFines) are a
separate mechanic from bounties -- paid at ANY station the issuing
faction controls, no danger, no Interstellar Factors markup (confirmed
against the Elite Dangerous wiki) -- the opposite of a bounty's "avoid
that faction" requirement. Previously untracked entirely: CommitCrime only
read the Bounty field, so a real fine (e.g. "collidedAtSpeedInNoFireZone",
Fine:100, no Bounty field) never appeared anywhere in the app. Real
EventEngine, matching this repo's convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.core.fine_scanner import scan_active_fines


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_commit_crime_with_fine_tracks_active_fines(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "CommitCrime", "CrimeType": "collidedAtSpeedInNoFireZone",
        "Faction": "Elite United Worlds", "Fine": 100,
    })
    assert engine.state.active_fines == {"Elite United Worlds": 100}
    # A real Fine event carries no Bounty -- must not be tracked as one.
    assert engine.state.active_bounties == {}


def test_commit_crime_fine_does_not_affect_bounty_and_vice_versa(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "CommitCrime", "CrimeType": "murder",
        "Faction": "Some Faction", "Bounty": 5000,
    })
    assert engine.state.active_bounties == {"Some Faction": 5000}
    assert engine.state.active_fines == {}


def test_pay_fines_clears_specific_faction(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "CommitCrime", "Faction": "Faction A", "Fine": 100,
    })
    engine.process({
        "event": "CommitCrime", "Faction": "Faction B", "Fine": 200,
    })
    engine.process({"event": "PayFines", "Faction": "Faction A"})
    assert engine.state.active_fines == {"Faction B": 200}


def test_pay_fines_without_faction_clears_all(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "CommitCrime", "Faction": "Faction A", "Fine": 100})
    engine.process({"event": "PayFines"})
    assert engine.state.active_fines == {}


def test_scan_active_fines_reconstructs_from_journal_history(tmp_path):
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()
    log_file = journal_dir / "Journal.2026-08-22T120000.01.log"
    log_file.write_text(
        '{"event":"CommitCrime","CrimeType":"collidedAtSpeedInNoFireZone",'
        '"Faction":"Elite United Worlds","Fine":100}\n'
        '{"event":"CommitCrime","CrimeType":"dockingMinorTrespass",'
        '"Faction":"Some Other Faction","Fine":50}\n'
        '{"event":"PayFines","Faction":"Some Other Faction"}\n',
        encoding="utf-8",
    )
    result = scan_active_fines(journal_dir)
    assert result == {"Elite United Worlds": 100}
