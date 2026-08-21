"""PowerplayMerits gains, however large, must never be counted as a kill --
merit size can't distinguish a PP-enemy kill from PP commodity-trade
delivery, which also grants large single-gain merit chunks (confirmed
live: a dockside MarketSell of a PP trade good produced a 3960-merit
gain, previously miscounted as a phantom session kill under the old
>=30-merits-means-kill heuristic). session_kills now only ever comes from
an actual kill event -- Bounty, FactionKillBond, CommitCrime murder.
Real EventEngine, matching this repo's convention (see
test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_large_merit_gain_is_never_counted_as_kill(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "PowerplayMerits", "Power": "Aisling Duval",
        "MeritsGained": 3960, "TotalMerits": 1170762,
    })

    assert engine.state.session_kills == 0


def test_small_merit_gain_is_never_counted_as_kill(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "PowerplayMerits", "Power": "Aisling Duval",
        "MeritsGained": 7, "TotalMerits": 1166795,
    })

    assert engine.state.session_kills == 0


def test_bounty_still_counts_as_kill(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "Bounty", "TotalReward": 50000,
        "VictimFaction": "Some Faction", "timestamp": "2026-08-21T20:00:00Z",
    })

    assert engine.state.session_kills == 1
