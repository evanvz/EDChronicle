from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_design_dialog as design_mod  # noqa: E402
from edc.ui.panels.colonisation_panel import ColonisationPanel  # noqa: E402


def _state(system, addr):
    return SimpleNamespace(system=system, system_address=addr, system_x=None, system_y=None, system_z=None)


def test_button_needs_hub_and_current_system():
    panel = ColonisationPanel(MagicMock())
    assert not panel._my_system_btn.isEnabled()
    panel.eddatahub_url = "http://hub"
    assert not panel._my_system_btn.isEnabled()
    panel.refresh(_state("HIP 109508", 79196785019))
    assert panel._my_system_btn.isEnabled()


def test_button_opens_design_for_current_system(monkeypatch):
    made, loads, stops = [], [], []

    class Rec:
        def __init__(self, parent, hub_url, id64, name, repo=None):
            made.append((hub_url, id64, name, repo))

        def load(self, id64, name):
            loads.append((id64, name, self.hub_url))

        def stop(self):
            stops.append(1)

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr(design_mod, "ColonisationDesignDialog", Rec)
    repo = MagicMock()
    panel = ColonisationPanel(repo)
    panel.eddatahub_url = "http://hub"
    panel.refresh(_state("HIP 109508", 79196785019))
    panel._my_system_btn.click()
    assert made == [("http://hub", 79196785019, "HIP 109508", repo)]
    panel.eddatahub_url = "http://hub2"
    panel.refresh(_state("Sol", 10477373803))
    panel._my_system_btn.click()
    assert len(made) == 1
    assert loads == [(10477373803, "Sol", "http://hub2")]
    panel.stop_finder_dialog()
    assert stops == [1]
