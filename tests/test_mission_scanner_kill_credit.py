"""scan_active_missions() must reconstruct massacre kill progress
(kills_credited) from journal history, not just mission accept/complete
state -- otherwise a restart mid-mission resets displayed progress to 0
even though the game itself remembers it server-side."""
from edc.core.mission_scanner import scan_active_missions


def _write_journal(tmp_path, filename, lines):
    import json
    path = tmp_path / filename
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def test_credits_faction_kill_bond_kills_in_mission_system(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FSDJump", "StarSystem": "Rho Ophiuchi Sector DV-Y b0"},
        {"event": "MissionAccepted", "MissionID": 1, "TargetFaction": "The Allied Commission",
         "DestinationSystem": "Rho Ophiuchi Sector DV-Y b0", "KillCount": 32},
        {"event": "FactionKillBond", "Reward": 62295, "AwardingFaction": "Elite United Worlds",
         "VictimFaction": "The Allied Commission"},
        {"event": "FactionKillBond", "Reward": 41359, "AwardingFaction": "Elite United Worlds",
         "VictimFaction": "The Allied Commission"},
    ])
    active = scan_active_missions(tmp_path)
    assert active[1]["kills_credited"] == 2


def test_ignores_kills_before_mission_accepted(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FSDJump", "StarSystem": "Rho Ophiuchi Sector DV-Y b0"},
        {"event": "FactionKillBond", "Reward": 62295, "AwardingFaction": "Elite United Worlds",
         "VictimFaction": "The Allied Commission"},
        {"event": "MissionAccepted", "MissionID": 1, "TargetFaction": "The Allied Commission",
         "DestinationSystem": "Rho Ophiuchi Sector DV-Y b0", "KillCount": 32},
    ])
    active = scan_active_missions(tmp_path)
    assert active[1]["kills_credited"] == 0


def test_ignores_kills_in_a_different_system(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FSDJump", "StarSystem": "Rho Ophiuchi Sector DV-Y b0"},
        {"event": "MissionAccepted", "MissionID": 1, "TargetFaction": "The Allied Commission",
         "DestinationSystem": "Rho Ophiuchi Sector DV-Y b0", "KillCount": 32},
        {"event": "FSDJump", "StarSystem": "Some Other System"},
        {"event": "FactionKillBond", "Reward": 62295, "AwardingFaction": "Elite United Worlds",
         "VictimFaction": "The Allied Commission"},
    ])
    active = scan_active_missions(tmp_path)
    assert active[1]["kills_credited"] == 0


def test_bounty_and_faction_kill_bond_both_credit(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FSDJump", "StarSystem": "Rho Ophiuchi Sector DV-Y b0"},
        {"event": "MissionAccepted", "MissionID": 1, "TargetFaction": "The Allied Commission",
         "DestinationSystem": "Rho Ophiuchi Sector DV-Y b0", "KillCount": 32},
        {"event": "Bounty", "TotalReward": 5000, "VictimFaction": "The Allied Commission"},
        {"event": "FactionKillBond", "Reward": 62295, "AwardingFaction": "Elite United Worlds",
         "VictimFaction": "The Allied Commission"},
    ])
    active = scan_active_missions(tmp_path)
    assert active[1]["kills_credited"] == 2
