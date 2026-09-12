"""MainWindow._refresh_bounty_status() -- called from the 75ms-debounced
_refresh_hud() on essentially every tick while a bounty is outstanding, it
used to re-run find_closest_interstellar_factors()'s O(24,783)-candidate
SQL query every single call. Confirmed live (py-spy) as a multi-minute
freeze during combat. The candidate set only depends on which factions
are excluded, not the ship's position, so it's now cached per
exclude_factions set; only the cheap Python closest-distance pass runs
fresh every tick."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(x=0.0, y=0.0, z=0.0, active_bounties=None, get_candidates_calls=None):
    calls = get_candidates_calls if get_candidates_calls is not None else []

    def _get_candidates(exclude_factions):
        calls.append(frozenset(exclude_factions))
        return ["candidate-row"]

    def _closest(candidates, x, y, z, exclude_factions=None):
        return {"candidates": candidates, "pos": (x, y, z)}

    return SimpleNamespace(
        state=SimpleNamespace(
            active_bounties=active_bounties or {"Faction A": 1000},
            bounty_last_commit={},
            system_x=x, system_y=y, system_z=z,
            closest_interstellar_factors=None,
        ),
        repo=SimpleNamespace(
            get_facilitator_candidates=_get_candidates,
            closest_facilitator_from_candidates=_closest,
        ),
        _if_candidates=[],
        _if_candidates_key=frozenset(),
        _calls=calls,
    )


def test_first_call_queries_candidates():
    fake_self = _fake_self()
    MainWindow._refresh_bounty_status(fake_self)
    assert fake_self._calls == [frozenset({"Faction A"})]


def test_repeat_call_same_factions_does_not_requery():
    fake_self = _fake_self()
    MainWindow._refresh_bounty_status(fake_self)
    MainWindow._refresh_bounty_status(fake_self)
    assert fake_self._calls == [frozenset({"Faction A"})]


def test_position_change_alone_does_not_requery():
    fake_self = _fake_self()
    MainWindow._refresh_bounty_status(fake_self)
    fake_self.state.system_x = 500.0
    MainWindow._refresh_bounty_status(fake_self)
    assert fake_self._calls == [frozenset({"Faction A"})]
    assert fake_self.state.closest_interstellar_factors["pos"] == (500.0, 0.0, 0.0)


def test_faction_set_change_requeries():
    fake_self = _fake_self()
    MainWindow._refresh_bounty_status(fake_self)
    fake_self.state.active_bounties = {"Faction B": 500}
    MainWindow._refresh_bounty_status(fake_self)
    assert fake_self._calls == [frozenset({"Faction A"}), frozenset({"Faction B"})]
