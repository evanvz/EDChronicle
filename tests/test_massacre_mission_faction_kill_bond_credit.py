"""Massacre mission kill-count progress must credit from FactionKillBond,
not just Bounty -- a CZ/war kill against a faction with no individual
bounty on the ship pays out as FactionKillBond, never fires Bounty at
all (confirmed live: 8 straight FactionKillBond events, zero Bounty,
after accepting a massacre mission against a war-enemy faction)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _accept_mission(engine, mission_id=1, target_faction="The Allied Commission",
                     system="Rho Ophiuchi Sector DV-Y b0", kill_count=32):
    engine.process({
        "timestamp": "2026-09-04T18:32:37Z", "event": "MissionAccepted",
        "MissionID": mission_id, "TargetFaction": target_faction,
        "DestinationSystem": system, "KillCount": kill_count,
        "Name": "Mission_Massacre_Conflict_CivilWar",
    })
    engine.state.system = system


def _kill_bond(reward, victim_faction, ts="2026-09-04T18:43:23Z"):
    return {
        "timestamp": ts, "event": "FactionKillBond", "Reward": reward,
        "AwardingFaction": "Elite United Worlds", "VictimFaction": victim_faction,
    }


def test_faction_kill_bond_credits_matching_massacre_mission(tmp_path):
    engine = _engine(tmp_path)
    _accept_mission(engine)

    engine.process(_kill_bond(62295, "The Allied Commission"))

    assert engine.state.active_missions[1]["kills_credited"] == 1


def test_faction_kill_bond_credits_only_one_stacked_mission_per_kill(tmp_path):
    # Not every stacked mission simultaneously -- confirmed wrong live
    # (see credit_massacre_kill's docstring): a kill credits only the
    # oldest-accepted matching mission not yet at its kill_count.
    engine = _engine(tmp_path)
    _accept_mission(engine, mission_id=1)
    _accept_mission(engine, mission_id=2)

    engine.process(_kill_bond(62295, "The Allied Commission"))

    assert engine.state.active_missions[1]["kills_credited"] == 1
    assert engine.state.active_missions[2]["kills_credited"] == 0


def test_faction_kill_bond_moves_to_next_stacked_mission_once_first_is_capped(tmp_path):
    engine = _engine(tmp_path)
    _accept_mission(engine, mission_id=1, kill_count=1)
    _accept_mission(engine, mission_id=2, kill_count=1)

    engine.process(_kill_bond(62295, "The Allied Commission", ts="2026-09-04T18:43:23Z"))
    engine.process(_kill_bond(41359, "The Allied Commission", ts="2026-09-04T18:49:38Z"))

    assert engine.state.active_missions[1]["kills_credited"] == 1
    assert engine.state.active_missions[2]["kills_credited"] == 1


def test_faction_kill_bond_does_not_credit_mismatched_faction(tmp_path):
    engine = _engine(tmp_path)
    _accept_mission(engine, target_faction="The Allied Commission")

    engine.process(_kill_bond(62295, "Some Other Faction"))

    assert engine.state.active_missions[1]["kills_credited"] == 0


def test_faction_kill_bond_does_not_overcredit_past_kill_count(tmp_path):
    engine = _engine(tmp_path)
    _accept_mission(engine, kill_count=1)

    engine.process(_kill_bond(62295, "The Allied Commission", ts="2026-09-04T18:43:23Z"))
    engine.process(_kill_bond(41359, "The Allied Commission", ts="2026-09-04T18:49:38Z"))

    assert engine.state.active_missions[1]["kills_credited"] == 1
