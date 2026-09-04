"""state.active_combat_bonds -- per-AwardingFaction unredeemed combat bond
total, separate from combat_unsold_total (which lumps bounty vouchers and
combat bonds together). A combat bond can only be redeemed at a station
the awarding faction controls (via Contacts, not Interstellar Factors),
so knowing which faction each bond belongs to is what lets the app point
at the right station. Real EventEngine, real journal data shapes (both
FactionKillBond and RedeemVoucher(Type="CombatBond") confirmed live)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _kill_bond(reward, faction, victim="Some Enemy Faction", ts="2026-09-04T10:00:00Z"):
    return {
        "timestamp": ts, "event": "FactionKillBond", "Reward": reward,
        "AwardingFaction": faction, "VictimFaction": victim,
    }


def test_faction_kill_bond_accumulates_per_faction(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_kill_bond(20611, "Elite United Worlds"))
    engine.process(_kill_bond(37732, "Elite United Worlds", ts="2026-09-04T10:01:00Z"))

    assert engine.state.active_combat_bonds == {"Elite United Worlds": 58343}


def test_faction_kill_bond_tracks_separate_factions_independently(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_kill_bond(20611, "Faction A"))
    engine.process(_kill_bond(37732, "Faction B", ts="2026-09-04T10:01:00Z"))

    assert engine.state.active_combat_bonds == {"Faction A": 20611, "Faction B": 37732}


def test_redeem_voucher_clears_only_the_redeemed_faction(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_kill_bond(20611, "Faction A"))
    engine.process(_kill_bond(37732, "Faction B", ts="2026-09-04T10:01:00Z"))

    engine.process({
        "timestamp": "2026-09-04T10:05:00Z", "event": "RedeemVoucher",
        "Type": "CombatBond", "Amount": 20611, "Faction": "Faction A",
    })

    assert engine.state.active_combat_bonds == {"Faction B": 37732}


def test_bounty_type_redeem_voucher_does_not_touch_combat_bonds(tmp_path):
    # RedeemVoucher Type="bounty" is a different voucher type (bounty
    # kill rewards, not combat bonds) -- must not clear active_combat_bonds.
    engine = _engine(tmp_path)
    engine.process(_kill_bond(20611, "Faction A"))

    engine.process({
        "timestamp": "2026-09-04T10:05:00Z", "event": "RedeemVoucher",
        "Type": "bounty", "Amount": 5000, "Factions": [{"Faction": "Faction A", "Amount": 5000}],
    })

    assert engine.state.active_combat_bonds == {"Faction A": 20611}


def test_duplicate_faction_kill_bond_event_not_double_counted(tmp_path):
    # Same dedup guard combat_unsold_total already relies on (journal
    # replay / bootstrap catch-up can re-process the same line).
    engine = _engine(tmp_path)
    event = _kill_bond(20611, "Faction A")
    engine.process(event)
    engine.process(dict(event))

    assert engine.state.active_combat_bonds == {"Faction A": 20611}
