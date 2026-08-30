"""Dying while wanted sends you to the nearest Detention Centre, which
forcibly pays off every accumulated bounty and fine as part of the
resurrection -- no separate PayBounties/PayFines event fires for it.
Confirmed live against a real journal: a Resurrect event's Cost (2000cr)
exactly matched two outstanding on-foot murder bounties (2x1000cr), with
the very next Location event landing at a
SystemGovernment=$government_Prison; station -- yet nothing in this app
ever cleared the bounty afterward, since it only ever watched for
PayBounties/PayFines."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.core.bounty_scanner import scan_active_bounties_with_dates
from edc.core.fine_scanner import scan_active_fines


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


# --- live EventEngine ---

def test_resurrect_clears_active_bounties(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "CommitCrime", "CrimeType": "onFoot_murder",
        "Faction": "Official Iah Bulu Freedom Party", "Bounty": 1000,
    })
    engine.process({"event": "Died", "KillerName": "Someone"})
    engine.process({"event": "Resurrect", "Option": "recover", "Cost": 1000, "Bankrupt": False})
    assert engine.state.active_bounties == {}
    assert engine.state.bounty_last_commit == {}


def test_resurrect_clears_active_fines_too(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "CommitCrime", "Faction": "Some Faction", "Fine": 200})
    engine.process({"event": "Resurrect", "Option": "recover", "Cost": 200, "Bankrupt": False})
    assert engine.state.active_fines == {}


def test_resurrect_with_no_outstanding_bounty_is_a_no_op(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Resurrect", "Option": "rebuy", "Cost": 50000, "Bankrupt": False})
    assert engine.state.active_bounties == {}
    assert engine.state.active_fines == {}


# --- historical scan reconstruction (bounty_scanner.py) ---

def test_scan_active_bounties_clears_on_resurrect(tmp_path):
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()
    (journal_dir / "Journal.2026-08-23T191140.01.log").write_text(
        '{"timestamp":"2026-08-23T18:01:19Z","event":"CommitCrime","CrimeType":"onFoot_murder",'
        '"Faction":"Official Iah Bulu Freedom Party","Victim":"Aura Padilla","Bounty":1000}\n'
        '{"timestamp":"2026-08-23T18:01:49Z","event":"Died","KillerName":"Arleth Powell"}\n'
        '{"timestamp":"2026-08-23T18:01:51Z","event":"CommitCrime","CrimeType":"onFoot_murder",'
        '"Faction":"Official Iah Bulu Freedom Party","Victim":"Bianca Haynes","Bounty":1000}\n'
        '{"timestamp":"2026-08-23T18:02:38Z","event":"Resurrect","Option":"recover","Cost":2000,"Bankrupt":false}\n',
        encoding="utf-8",
    )
    active, last_commit = scan_active_bounties_with_dates(journal_dir)
    assert active == {}
    assert last_commit == {}


def test_scan_active_bounties_keeps_unrelated_later_bounty_after_resurrect(tmp_path):
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()
    (journal_dir / "Journal.2026-08-23T180000.01.log").write_text(
        '{"timestamp":"2026-08-23T18:01:19Z","event":"CommitCrime",'
        '"Faction":"Faction A","Bounty":1000}\n'
        '{"timestamp":"2026-08-23T18:02:38Z","event":"Resurrect","Option":"recover","Cost":1000,"Bankrupt":false}\n'
        '{"timestamp":"2026-08-24T10:00:00Z","event":"CommitCrime",'
        '"Faction":"Faction B","Bounty":500}\n',
        encoding="utf-8",
    )
    active, _ = scan_active_bounties_with_dates(journal_dir)
    assert active == {"Faction B": 500}


# --- historical scan reconstruction (fine_scanner.py) ---

def test_scan_active_fines_clears_on_resurrect(tmp_path):
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()
    (journal_dir / "Journal.2026-08-23T180000.01.log").write_text(
        '{"event":"CommitCrime","Faction":"Faction A","Fine":100}\n'
        '{"event":"Resurrect","Option":"recover","Cost":100,"Bankrupt":false}\n',
        encoding="utf-8",
    )
    assert scan_active_fines(journal_dir) == {}
