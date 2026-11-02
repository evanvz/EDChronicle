"""Raven Colonial / EDSM push: config switches and the journal dispatch gate."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.config import AppConfig, ConfigStore
from edc.core.edsm_push import with_transient
from edc.core.push_credentials import EDSM, RAVEN
from edc.ui.main_window import MainWindow

DEPOT = {"event": "ColonisationConstructionDepot", "MarketID": 1, "ResourcesRequired": []}


def test_config_push_defaults_off(tmp_path):
    cfg = ConfigStore(tmp_path).load()
    assert cfg.raven_push_enabled is False
    assert cfg.edsm_push_enabled is False
    assert cfg.edsm_commander_name == ""


def test_config_push_round_trip(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = AppConfig()
    cfg.raven_push_enabled = True
    cfg.edsm_push_enabled = True
    cfg.edsm_commander_name = "Bob"
    store.save(cfg)
    loaded = store.load()
    assert (loaded.raven_push_enabled, loaded.edsm_push_enabled, loaded.edsm_commander_name) == (True, True, "Bob")


def _fake_self(replaying=False, commander="B0B R0GERS"):
    cfg = AppConfig()
    cfg.raven_push_enabled = True
    cfg.edsm_push_enabled = True
    state = SimpleNamespace(commander=commander, system="Sol", system_x=1.0, system_y=2.0, system_z=3.0,
                            system_address=10477373803, station_name="Abraham Lincoln", ship_id=7)
    return SimpleNamespace(cfg=cfg, state=state, _replaying=replaying,
                           _raven_pusher=MagicMock(), _edsm_pusher=MagicMock(),
                           _push_names={RAVEN: "B0B R0GERS", EDSM: "B0B R0GERS"})


def test_no_push_during_replay():
    fake_self = _fake_self(replaying=True)
    MainWindow._push_third_party(fake_self, DEPOT)
    fake_self._raven_pusher.submit.assert_not_called()
    fake_self._edsm_pusher.submit.assert_not_called()


def test_no_push_for_other_commander():
    fake_self = _fake_self(commander="Alt")
    MainWindow._push_third_party(fake_self, DEPOT)
    fake_self._raven_pusher.submit.assert_not_called()
    fake_self._edsm_pusher.submit.assert_not_called()


def test_push_when_live_and_matching():
    fake_self = _fake_self()
    MainWindow._push_third_party(fake_self, DEPOT)
    fake_self._raven_pusher.submit.assert_called_once_with(DEPOT, 10477373803)
    fake_self._edsm_pusher.submit.assert_called_once_with(
        with_transient(DEPOT, "Sol", (1.0, 2.0, 3.0), "Abraham Lincoln", 7))


def test_raven_ignores_other_events():
    fake_self = _fake_self()
    MainWindow._push_third_party(fake_self, {"event": "FSDJump"})
    fake_self._raven_pusher.submit.assert_not_called()
    fake_self._edsm_pusher.submit.assert_called_once()


def test_status_not_sent_to_edsm():
    fake_self = _fake_self()
    MainWindow._push_third_party(fake_self, {"event": "Status"})
    fake_self._edsm_pusher.submit.assert_not_called()
    MainWindow._push_third_party(fake_self, {"event": "FSDJump"})
    fake_self._edsm_pusher.submit.assert_called_once()


def test_edsm_save_refused_without_commander():
    label = MagicMock()
    fake_self = SimpleNamespace(state=SimpleNamespace(commander=None), _push_checks={}, db=MagicMock(),
                                edsm_key_edit=SimpleNamespace(text=lambda: "k"), _push_label=lambda s: label)
    MainWindow._on_push_key_check(fake_self, EDSM, True)
    label.setText.assert_called_once_with("Start the game first so the commander is known")
    assert fake_self._push_checks == {}
    fake_self.db.execute.assert_not_called()


def test_restart_pusher_does_not_wait_for_old_sender(monkeypatch):
    import edc.ui.main_window as mw
    monkeypatch.setattr(mw, "load_key", lambda db, service: None)
    old = MagicMock()
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    fake_self = SimpleNamespace(_edsm_pusher=old, db=db, cfg=AppConfig(), _push_label=lambda s: MagicMock())
    MainWindow._restart_pusher(fake_self, EDSM)
    old.stop.assert_called_once_with(wait=False)
    assert fake_self._edsm_pusher is None
