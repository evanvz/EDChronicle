from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def test_died_clears_data_and_bounties_keeps_bonds(tmp_path):
    # 2026-11-11: ship destroyed holding ~94M Cr of data; the app kept showing it after rebuy
    eng = EventEngine(GameState(), tmp_path)
    eng.state.exploration_unsold_total_est = 94_251_099
    eng.state.exobiology_unsold_total_est = 5_000_000
    eng.process({"timestamp": "2026-11-11T15:00:00Z", "event": "Bounty", "TotalReward": 5000})
    eng.process({"timestamp": "2026-11-11T15:45:22Z", "event": "FactionKillBond", "Reward": 20746,
                 "AwardingFaction": "Sorbago Mastopolos Mining Inc"})
    eng.process({"timestamp": "2026-11-11T16:29:45Z", "event": "Died", "KillerName": "Khan Port"})
    assert eng.state.exploration_unsold_total_est == 0
    assert eng.state.exobiology_unsold_total_est == 0
    assert eng.state.combat_unsold_total == 20746
    assert eng.state.active_combat_bonds == {"Sorbago Mastopolos Mining Inc": 20746}
