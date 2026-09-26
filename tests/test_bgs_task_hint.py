"""Overview HUD squadron-task hint + MainWindow refresh wiring for the BGS
Tasks tracker."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from edc.config import AppConfig
from edc.ui.main_window import MainWindow
from edc.ui.panels.overview_panel import OverviewPanel
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_app = QApplication.instance() or QApplication(sys.argv)


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (12345, 'Ekono')")
    return repo


def _fake_self(repo, system_address=12345, system="Ekono"):
    hints = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address, system=system),
        repo=repo, cfg=AppConfig(),
        player_faction_panel=SimpleNamespace(_latest_known_tick=None),
        overview_panel=SimpleNamespace(set_bgs_task_hint=hints.append),
        _hints=hints,
    )


def test_hint_shows_task_for_current_system(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    fake_self = _fake_self(repo)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == ["Squadron task: Boost Elite United Worlds — tier score 0/25"]


def test_hint_empty_in_a_system_without_tasks(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    fake_self = _fake_self(repo, system_address=999)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == [""]


def test_hint_empty_without_a_current_system(tmp_path):
    fake_self = _fake_self(_repo(tmp_path), system_address=None)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == [""]


def test_hint_resolves_a_task_added_before_the_system_was_known(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("Kanuket", "note", note="watch faction")
    fake_self = _fake_self(repo, system_address=777, system="Kanuket")
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == ["Squadron task: Note: watch faction"]


def test_overview_hint_label_visibility():
    panel = OverviewPanel()
    panel.set_bgs_task_hint("Squadron task: Note: x")
    assert panel.bgs_task_badge.text() == "Squadron task: Note: x"
    assert not panel.bgs_task_badge.isHidden()
    panel.set_bgs_task_hint("")
    assert panel.bgs_task_badge.isHidden()


def test_notify_pushes_panel_and_hint():
    calls = []
    fake_self = SimpleNamespace(
        player_faction_panel=SimpleNamespace(notify_bgs_activity=lambda: calls.append("panel")),
        _refresh_bgs_task_hint=lambda: calls.append("hint"),
    )
    MainWindow._notify_bgs_activity(fake_self)
    # Hint first: it links tasks to the system just arrived in, so the
    # window's refresh right after already sees the link.
    assert calls == ["hint", "panel"]


def _dispatch_fake_self(replaying):
    fake_self = MagicMock()
    fake_self._replaying = replaying
    fake_self.engine.process.return_value = (MagicMock(), [])
    fake_self.cfg.eddn_contribute_enabled = False
    return fake_self


def test_activity_event_notifies_when_live():
    fake_self = _dispatch_fake_self(replaying=False)
    MainWindow._on_event(fake_self, {"event": "RedeemVoucher", "Type": "bounty", "Amount": 1, "timestamp": "2026-09-26T10:00:00Z"})
    fake_self._notify_bgs_activity.assert_called_once_with()


def test_activity_event_does_not_notify_during_replay():
    fake_self = _dispatch_fake_self(replaying=True)
    MainWindow._on_event(fake_self, {"event": "FSDJump", "timestamp": "2026-09-26T10:00:00Z"})
    fake_self._notify_bgs_activity.assert_not_called()


def test_bootstrap_end_refreshes_hint():
    fake_self = _dispatch_fake_self(replaying=True)
    MainWindow._on_event(fake_self, {"event": "_BootstrapEnd"})
    fake_self._refresh_bgs_task_hint.assert_called_once_with()
