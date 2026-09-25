"""EventEngine's FactionKillBond handling sets state.last_cz_credit
exactly when _credit_cz_kill applies a new tally increment -- a one-shot
signal main_window.py reads right after engine.process() to persist the
credit for the session BGS activity report (the cumulative
state.cz_kills dict alone can't tell a caller whether THIS event just
added a new kill). Real EventEngine, same construction and SupercruiseExit
trigger as test_active_combat_bonds.py's sibling in-memory-tally tests."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _bond_event(reward, awarding_faction="Elite United Worlds", ts="2026-09-25T10:00:00Z"):
    return {
        "event": "FactionKillBond", "timestamp": ts, "Reward": reward,
        "AwardingFaction": awarding_faction, "VictimFaction": "Rival Faction",
    }


def _enter_space_cz(engine, size_suffix="High", ts="2026-09-25T09:59:00Z"):
    engine.process({
        "event": "SupercruiseExit", "timestamp": ts,
        "Type": f"$Warzone_PointRace_{size_suffix};", "StarSystem": "Ekono", "SystemAddress": 12345,
    })


def _enter_ground_cz(engine, ts="2026-09-25T09:59:00Z"):
    engine.process({
        "event": "ApproachSettlement", "timestamp": ts,
        "Name": "Justice Reworked Hub", "SystemAddress": 12345,
    })


def test_last_cz_credit_is_set_when_a_space_cz_kill_is_confirmed(tmp_path):
    engine = _engine(tmp_path)
    _enter_space_cz(engine, "High")
    state, _ = engine.process(_bond_event(50000))
    assert state.last_cz_credit == {
        "faction_name": "Elite United Worlds", "zone_type": "space", "size": "h",
    }


def test_last_cz_credit_is_none_when_no_pending_cz_window(tmp_path):
    engine = _engine(tmp_path)
    state, _ = engine.process(_bond_event(50000))
    assert state.last_cz_credit is None


def test_last_cz_credit_resets_between_events(tmp_path):
    engine = _engine(tmp_path)
    _enter_space_cz(engine, "High")
    state, _ = engine.process(_bond_event(50000, ts="2026-09-25T10:00:00Z"))
    assert state.last_cz_credit is not None
    state, _ = engine.process(_bond_event(50000, ts="2026-09-25T10:05:00Z"))  # no fresh pending CZ this time
    assert state.last_cz_credit is None


def test_last_cz_credit_not_set_again_when_ground_cz_kill_size_upgrades(tmp_path):
    """A ground CZ kill's bond can be reported low first (team-split reward)
    then corrected upward for the SAME kill. last_cz_credit must fire only
    on the first detection -- otherwise main_window.py's persistence hook
    inserts a second row in faction_cz_kills for one real kill."""
    engine = _engine(tmp_path)
    _enter_ground_cz(engine)
    # First bond: below the low/medium threshold -> "l", first detection.
    state, _ = engine.process(_bond_event(4000, ts="2026-09-25T10:00:00Z"))
    assert state.last_cz_credit == {
        "faction_name": "Elite United Worlds", "zone_type": "ground", "size": "l",
    }
    # Second bond for the SAME pending CZ: crosses into medium -> upgrade.
    state, _ = engine.process(_bond_event(20000, ts="2026-09-25T10:00:05Z"))
    assert state.last_cz_credit is None
    # In-memory tally still re-buckets correctly: one medium kill, no low.
    tally = state.cz_kills["Elite United Worlds"]
    assert tally.get("ground_m") == 1
    assert tally.get("ground_l", 0) == 0
