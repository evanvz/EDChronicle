"""PlayerFactionPanel._open_session_activity_dialog() -- lazily creates
the SessionActivityDialog once, reuses it on subsequent opens. Fake
self + a fake dialog class (avoids constructing a real QDialog), same
pattern as test_faction_expansion_live_push.py."""
from types import SimpleNamespace

from edc.ui.panels.player_faction_panel import PlayerFactionPanel


def _fake_dialog_cls():
    instances = []

    class _FakeDialog:
        def __init__(self, panel):
            self.panel = panel
            self.shown = False
            self.raised = False
            self.activated = False
            instances.append(self)

        def show(self):
            self.shown = True

        def raise_(self):
            self.raised = True

        def activateWindow(self):
            self.activated = True

    return _FakeDialog, instances


def test_creates_the_dialog_on_first_open(monkeypatch):
    fake_cls, instances = _fake_dialog_cls()
    monkeypatch.setattr("edc.ui.panels.player_faction_panel.SessionActivityDialog", fake_cls)
    fake_self = SimpleNamespace(_session_activity_dialog=None)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    assert len(instances) == 1
    assert instances[0].shown and instances[0].raised and instances[0].activated
    assert fake_self._session_activity_dialog is instances[0]


def test_reuses_the_dialog_on_second_open(monkeypatch):
    fake_cls, instances = _fake_dialog_cls()
    monkeypatch.setattr("edc.ui.panels.player_faction_panel.SessionActivityDialog", fake_cls)
    fake_self = SimpleNamespace(_session_activity_dialog=None)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    assert len(instances) == 1
