"""scan_unredeemed_combat_total() -- one-shot full-history reconstruction
of both the combined combat_unsold_total (bounty vouchers + combat bonds)
and the per-AwardingFaction active_combat_bonds breakdown, so an
unredeemed bond survives an app restart the same way it survives in-game
until actually redeemed."""
from edc.core.combat_bond_scanner import scan_unredeemed_combat_total


def _write_journal(tmp_path, filename, lines):
    import json
    path = tmp_path / filename
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def test_missing_journal_dir_returns_empty(tmp_path):
    total, bonds = scan_unredeemed_combat_total(tmp_path / "does_not_exist")
    assert total == 0
    assert bonds == {}


def test_faction_kill_bond_accumulates_total_and_per_faction(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FactionKillBond", "Reward": 20611, "AwardingFaction": "Faction A"},
        {"event": "FactionKillBond", "Reward": 37732, "AwardingFaction": "Faction A"},
        {"event": "FactionKillBond", "Reward": 15000, "AwardingFaction": "Faction B"},
    ])
    total, bonds = scan_unredeemed_combat_total(tmp_path)
    assert total == 73343
    assert bonds == {"Faction A": 58343, "Faction B": 15000}


def test_bounty_event_adds_to_total_but_not_per_faction_bonds(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "Bounty", "TotalReward": 5000},
        {"event": "FactionKillBond", "Reward": 10000, "AwardingFaction": "Faction A"},
    ])
    total, bonds = scan_unredeemed_combat_total(tmp_path)
    assert total == 15000
    assert bonds == {"Faction A": 10000}


def test_redeem_voucher_combat_bond_clears_only_that_faction(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FactionKillBond", "Reward": 10000, "AwardingFaction": "Faction A"},
        {"event": "FactionKillBond", "Reward": 20000, "AwardingFaction": "Faction B"},
        {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 10000, "Faction": "Faction A"},
    ])
    total, bonds = scan_unredeemed_combat_total(tmp_path)
    assert total == 0  # combined total resets on any bounty/CombatBond redemption
    assert bonds == {"Faction B": 20000}


def test_redeem_voucher_bounty_type_clears_total_but_not_per_faction_bonds(tmp_path):
    _write_journal(tmp_path, "Journal.01.log", [
        {"event": "FactionKillBond", "Reward": 10000, "AwardingFaction": "Faction A"},
        {"event": "RedeemVoucher", "Type": "bounty", "Amount": 10000, "Factions": [{"Faction": "Faction A", "Amount": 10000}]},
    ])
    total, bonds = scan_unredeemed_combat_total(tmp_path)
    assert total == 0
    assert bonds == {"Faction A": 10000}


def test_replays_multiple_files_in_chronological_order(tmp_path):
    _write_journal(tmp_path, "Journal.2026-09-01.log", [
        {"event": "FactionKillBond", "Reward": 10000, "AwardingFaction": "Faction A"},
    ])
    _write_journal(tmp_path, "Journal.2026-09-02.log", [
        {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 10000, "Faction": "Faction A"},
        {"event": "FactionKillBond", "Reward": 5000, "AwardingFaction": "Faction A"},
    ])
    total, bonds = scan_unredeemed_combat_total(tmp_path)
    assert bonds == {"Faction A": 5000}
