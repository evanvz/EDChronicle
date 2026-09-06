"""MainWindow._save_colonisation_depot() -- Frontier fires
ColonisationConstructionDepot every 15s while docked regardless of
whether anything changed, so a dedup guard on (progress, complete,
resources) per MarketID must skip the DB write (and tell the caller to
skip the panel refresh) on a repeat tick with nothing new."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system="Sol", station="Orbital Depot"):
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(system=system, current_market_station=station, system_address=123),
        repo=SimpleNamespace(save_colonisation_depot_visit=lambda **kw: saved.append(kw)),
        _colonisation_depot_last_seen={},
        _saved=saved,
    )


def _depot_event(market_id=1, progress=0.5, complete=False, resources=None):
    return {
        "event": "ColonisationConstructionDepot", "MarketID": market_id,
        "ConstructionProgress": progress, "ConstructionComplete": complete,
        "ResourcesRequired": resources or [],
    }


def test_first_tick_saves_and_returns_true():
    fake_self = _fake_self()
    changed = MainWindow._save_colonisation_depot(fake_self, _depot_event())
    assert changed is True
    assert len(fake_self._saved) == 1


def test_repeat_tick_with_no_change_is_skipped():
    fake_self = _fake_self()
    MainWindow._save_colonisation_depot(fake_self, _depot_event())
    changed = MainWindow._save_colonisation_depot(fake_self, _depot_event())
    assert changed is False
    assert len(fake_self._saved) == 1


def test_progress_change_triggers_a_new_save():
    fake_self = _fake_self()
    MainWindow._save_colonisation_depot(fake_self, _depot_event(progress=0.5))
    changed = MainWindow._save_colonisation_depot(fake_self, _depot_event(progress=0.6))
    assert changed is True
    assert len(fake_self._saved) == 2


def test_different_market_ids_tracked_independently():
    fake_self = _fake_self()
    MainWindow._save_colonisation_depot(fake_self, _depot_event(market_id=1))
    changed = MainWindow._save_colonisation_depot(fake_self, _depot_event(market_id=2))
    assert changed is True
    assert len(fake_self._saved) == 2


def test_missing_market_id_returns_false():
    fake_self = _fake_self()
    changed = MainWindow._save_colonisation_depot(fake_self, {"event": "ColonisationConstructionDepot"})
    assert changed is False
    assert fake_self._saved == []


def test_missing_system_or_station_returns_false():
    fake_self = _fake_self(system="", station="")
    changed = MainWindow._save_colonisation_depot(fake_self, _depot_event())
    assert changed is False
    assert fake_self._saved == []
