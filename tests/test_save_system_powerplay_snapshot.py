"""MainWindow._save_system_powerplay_snapshot() -- persists the journal's
own live PowerplayState* fields (self.state), called from the
FSDJump/Location handler. Fake self, same pattern as
test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(**state_kwargs):
    saved = []
    defaults = dict(
        system_address=12345, system="Ekono", system_powerplay_state="Stronghold",
        system_powerplay_control_progress=0.268642, system_powerplay_reinforcement=908,
        system_powerplay_undermining=4666, system_controlling_power="Aisling Duval",
        system_powers=["Aisling Duval"], factions_timestamp="2026-09-24T21:34:20Z",
    )
    defaults.update(state_kwargs)
    return SimpleNamespace(
        state=SimpleNamespace(**defaults),
        repo=SimpleNamespace(save_system_powerplay_snapshot=lambda **kw: saved.append(kw)),
        _saved=saved,
    )


def test_saves_a_live_reading():
    fake_self = _fake_self()
    MainWindow._save_system_powerplay_snapshot(fake_self)
    assert fake_self._saved == [{
        "system_address": 12345, "system_name": "Ekono", "pp_state": "Stronghold",
        "control_progress": 0.268642, "reinforcement": 908, "undermining": 4666,
        "controlling_power": "Aisling Duval", "powers": ["Aisling Duval"],
        "data_timestamp": "2026-09-24T21:34:20Z",
    }]


def test_skipped_when_no_powerplay_state():
    fake_self = _fake_self(system_powerplay_state=None)
    MainWindow._save_system_powerplay_snapshot(fake_self)
    assert fake_self._saved == []


def test_skipped_when_no_system_address():
    fake_self = _fake_self(system_address=None)
    MainWindow._save_system_powerplay_snapshot(fake_self)
    assert fake_self._saved == []
