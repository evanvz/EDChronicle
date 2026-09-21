"""_RavenColonialDialog's nearest-source pad filtering -- pure logic
exercised via a fake self (SimpleNamespace), same pattern as
test_filter_enemy_pp.py, to avoid needing a real QApplication.

Ship-needs-at-least-X-pad semantics: a ship needing 'S' can use S/M/L
stations; a manual override of 'L' excludes S/M sources even if they're
nearer, since the ship being checked couldn't land there."""
from types import SimpleNamespace

from edc.ui.panels.colonisation_panel import _RavenColonialDialog


def _fake_dialog(sources_by_commodity, ship="anaconda", ship_pad="L", override=None,
                  ship_pad_table=None):
    pad_table = ship_pad_table or SimpleNamespace(pad_size_for=lambda s: ship_pad)
    panel = SimpleNamespace(
        _last_state=SimpleNamespace(ship=ship),
        _ship_pad_table=pad_table,
    )
    fs = SimpleNamespace(
        _panel=panel,
        _pad_combo=SimpleNamespace(currentData=lambda: override),
        _sources_by_commodity=sources_by_commodity,
    )
    fs._current_ship_pad = lambda: _RavenColonialDialog._current_ship_pad(fs)
    fs._effective_pad_filter = lambda: _RavenColonialDialog._effective_pad_filter(fs)
    return fs


def test_current_ship_pad_from_table():
    fs = _fake_dialog({}, ship="anaconda", ship_pad="L")
    assert _RavenColonialDialog._current_ship_pad(fs) == "L"


def test_current_ship_pad_none_when_no_table():
    fs = _fake_dialog({}, ship_pad_table=None)
    fs._panel._ship_pad_table = None
    assert _RavenColonialDialog._current_ship_pad(fs) is None


def test_effective_pad_filter_uses_ship_when_no_override():
    fs = _fake_dialog({}, ship_pad="M", override=None)
    assert _RavenColonialDialog._effective_pad_filter(fs) == "M"


def test_effective_pad_filter_prefers_manual_override():
    fs = _fake_dialog({}, ship_pad="M", override="S")
    assert _RavenColonialDialog._effective_pad_filter(fs) == "S"


def test_best_source_skips_pads_too_small_for_the_ship():
    sources = {
        "aluminium": [
            {"station_name": "Near Small", "pad_size": "S", "distance_ly": 1.0},
            {"station_name": "Far Large", "pad_size": "L", "distance_ly": 10.0},
        ]
    }
    fs = _fake_dialog(sources, ship_pad="L", override=None)
    best = _RavenColonialDialog._best_source_for(fs, "aluminium")
    assert best["station_name"] == "Far Large"


def test_best_source_returns_nearest_when_pad_unknown():
    sources = {
        "aluminium": [
            {"station_name": "Nearest", "pad_size": "S", "distance_ly": 1.0},
            {"station_name": "Farther", "pad_size": "L", "distance_ly": 10.0},
        ]
    }
    fs = _fake_dialog(sources, ship_pad=None, override=None)
    best = _RavenColonialDialog._best_source_for(fs, "aluminium")
    assert best["station_name"] == "Nearest"


def test_best_source_returns_none_when_nothing_qualifies():
    sources = {"aluminium": [{"station_name": "Only Small", "pad_size": "S", "distance_ly": 1.0}]}
    fs = _fake_dialog(sources, ship_pad="L", override=None)
    assert _RavenColonialDialog._best_source_for(fs, "aluminium") is None


def test_best_source_returns_none_for_unknown_commodity():
    fs = _fake_dialog({}, ship_pad="L")
    assert _RavenColonialDialog._best_source_for(fs, "unobtainium") is None
