"""MainWindow._compute_action_state() -- called from the 75ms-debounced
_refresh_hud() on essentially every journal event, it used to re-query
get_codex_species_sightings_for_system() every single call even when
system_address hadn't changed. Now cached per system_address; the cache
is invalidated on a system change (a natural cache miss) and by
_on_eddn_flush_finished (since the EDDN flush can write new sightings
for the current system with no other signal path to the HUD)."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system_address=123):
    calls = []

    def _get_sightings(addr):
        calls.append(addr)
        return {}

    return SimpleNamespace(
        cfg=SimpleNamespace(min_planet_value_100k=5, exo_high_value_m=2),
        exo_values=None,
        state=SimpleNamespace(system_address=system_address, bodies={}, rings={}),
        repo=SimpleNamespace(get_codex_species_sightings_for_system=_get_sightings),
        _spansh_rings_by_system={},
        _codex_sightings_cache={},
        _codex_sightings_cache_system=None,
        _calls=calls,
    )


def test_first_call_queries_sightings():
    fake_self = _fake_self()
    MainWindow._compute_action_state(fake_self)
    assert fake_self._calls == [123]


def test_repeat_call_same_system_does_not_requery():
    fake_self = _fake_self()
    MainWindow._compute_action_state(fake_self)
    MainWindow._compute_action_state(fake_self)
    assert fake_self._calls == [123]


def test_system_change_requeries():
    fake_self = _fake_self()
    MainWindow._compute_action_state(fake_self)
    fake_self.state.system_address = 456
    MainWindow._compute_action_state(fake_self)
    assert fake_self._calls == [123, 456]


def test_eddn_flush_finished_forces_requery():
    fake_self = _fake_self()
    MainWindow._compute_action_state(fake_self)
    MainWindow._on_eddn_flush_finished(fake_self)
    MainWindow._compute_action_state(fake_self)
    assert fake_self._calls == [123, 123]
