"""MarketPanel._filter_enemy_pp() -- pure logic exercised via a fake self
(SimpleNamespace), same pattern as test_odyssey_inventory.py, to avoid
needing a real QApplication for the QCheckBox.

EDSM's daily PowerPlay dump misses real systems entirely (confirmed live:
a system under live enemy control had zero rows anywhere in the dump), so
a system unresolved there falls back to a self._spansh_power_cache
populated by a background Spansh lookup -- this is the fix for that gap."""
from types import SimpleNamespace

from edc.ui.panels.market_panel import MarketPanel


def _fake_self(checked=True, my_power="Aisling Duval", edsm_powerplay=None,
                spansh_cache=None, spansh_pending=None):
    return SimpleNamespace(
        _exclude_enemy_pp_check=SimpleNamespace(isChecked=lambda: checked),
        _my_power=my_power,
        _edsm_powerplay=edsm_powerplay,
        _spansh_power_cache=spansh_cache if spansh_cache is not None else {},
        _spansh_power_pending=spansh_pending if spansh_pending is not None else set(),
        _resolve_unknown_pp_systems=lambda names: None,
    )


class _FakeEdsmPowerplay:
    def __init__(self, controllers):
        self._controllers = controllers

    def get_controller_by_name(self, system_name):
        return self._controllers.get(system_name)


def test_checkbox_unchecked_keeps_everything():
    fake_self = _fake_self(checked=False, edsm_powerplay=_FakeEdsmPowerplay(
        {"Enemy System": {"power": "Zemina Torval"}}))
    results = [{"system_name": "Enemy System"}]
    kept, excluded = MarketPanel._filter_enemy_pp(fake_self, results)
    assert kept == results
    assert excluded == 0


def test_edsm_known_enemy_system_excluded():
    fake_self = _fake_self(edsm_powerplay=_FakeEdsmPowerplay(
        {"Enemy System": {"power": "Zemina Torval"}}))
    results = [{"system_name": "Enemy System"}, {"system_name": "Friendly System"}]
    kept, excluded = MarketPanel._filter_enemy_pp(fake_self, results)
    assert kept == [{"system_name": "Friendly System"}]
    assert excluded == 1


def test_system_not_in_edsm_dump_falls_back_to_spansh_cache():
    # This is the exact live scenario: EDSM's get_controller_by_name
    # returns None (system missing from the dump entirely), but a prior
    # Spansh lookup already resolved it as enemy-controlled.
    fake_self = _fake_self(
        edsm_powerplay=_FakeEdsmPowerplay({}),
        spansh_cache={"arcadian": "Zemina Torval"},
    )
    results = [{"system_name": "Arcadian"}]
    kept, excluded = MarketPanel._filter_enemy_pp(fake_self, results)
    assert kept == []
    assert excluded == 1


def test_system_not_in_edsm_dump_and_not_yet_spansh_resolved_is_kept_and_queued():
    queued = []
    fake_self = _fake_self(edsm_powerplay=_FakeEdsmPowerplay({}))
    fake_self._resolve_unknown_pp_systems = lambda names: queued.append(names)
    results = [{"system_name": "Arcadian"}]
    kept, excluded = MarketPanel._filter_enemy_pp(fake_self, results)
    assert kept == results
    assert excluded == 0
    assert queued == [{"Arcadian"}]


def test_system_already_pending_spansh_lookup_not_requeued():
    queued = []
    fake_self = _fake_self(
        edsm_powerplay=_FakeEdsmPowerplay({}),
        spansh_pending={"arcadian"},
    )
    fake_self._resolve_unknown_pp_systems = lambda names: queued.append(names)
    results = [{"system_name": "Arcadian"}]
    MarketPanel._filter_enemy_pp(fake_self, results)
    assert queued == []


def test_spansh_cache_hit_matching_own_power_is_kept():
    fake_self = _fake_self(
        my_power="Aisling Duval",
        edsm_powerplay=_FakeEdsmPowerplay({}),
        spansh_cache={"home system": "Aisling Duval"},
    )
    results = [{"system_name": "Home System"}]
    kept, excluded = MarketPanel._filter_enemy_pp(fake_self, results)
    assert kept == results
    assert excluded == 0


def test_on_power_lookup_finished_caches_and_rerenders():
    rendered = {"results": False, "trade": False}
    fake_self = SimpleNamespace(
        _spansh_power_cache={}, _spansh_power_pending={"arcadian"},
        _last_results=[{"system_name": "Arcadian"}],
        _render_results=lambda: rendered.__setitem__("results", True),
        _render_trade_opportunities=lambda: rendered.__setitem__("trade", True),
    )
    MarketPanel._on_power_lookup_finished(fake_self, {"Arcadian": "Zemina Torval"})
    assert fake_self._spansh_power_cache == {"arcadian": "Zemina Torval"}
    assert "arcadian" not in fake_self._spansh_power_pending
    assert rendered == {"results": True, "trade": True}
