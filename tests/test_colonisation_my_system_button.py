from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_design_dialog as design_mod  # noqa: E402
from edc.ui.panels.colonisation_panel import ColonisationPanel  # noqa: E402


def _state(system, addr):
    return SimpleNamespace(system=system, system_address=addr, system_x=None, system_y=None, system_z=None)


def _repo(*systems):
    repo = MagicMock()
    repo.get_colonisation_depots.return_value = [
        {"id": i, "market_id": i, "system_address": a, "system_name": n, "station_name": "Site",
         "progress": 0.1, "complete": 0, "resources": []} for i, (n, a) in enumerate(systems, 1)]
    repo.get_system_coords_for_names.return_value = {}
    return repo


def test_button_needs_hub_and_an_own_system():
    panel = ColonisationPanel(_repo())
    panel.eddatahub_url = "http://hub"
    panel.refresh(_state("HIP 109508", 79196785019))
    assert not panel._my_system_btn.isEnabled()  # no construction site anywhere yet
    panel = ColonisationPanel(_repo(("HIP 109508", 79196785019)))
    panel.refresh(_state("Synuefe KV-B d14-58", 2003342133627))
    assert not panel._my_system_btn.isEnabled()
    panel.eddatahub_url = "http://hub"
    assert panel._my_system_btn.isEnabled()


def test_opens_current_system_if_own_else_first_own():
    # Live 2026-11-09: in Synuefe KV-B d14-58 (not a colonisation system) the window opened that system.
    panel = ColonisationPanel(_repo(("HIP 109508", 79196785019), ("HIP 1", 11)))
    panel.refresh(_state("Synuefe KV-B d14-58", 2003342133627))
    assert panel._my_system() == (79196785019, "HIP 109508")
    panel.refresh(_state("HIP 1", 11))
    assert panel._my_system() == (11, "HIP 1")


def test_button_opens_design_for_selected_system(monkeypatch):
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
    repo = _repo(("HIP 109508", 79196785019), ("Sol", 10477373803))
    panel = ColonisationPanel(repo)
    panel.eddatahub_url = "http://hub"
    panel.refresh(_state("Synuefe KV-B d14-58", 2003342133627))
    panel._my_system_btn.click()
    assert made == [("http://hub", 79196785019, "HIP 109508", repo)]
    panel.eddatahub_url = "http://hub2"
    panel.refresh(_state("Sol", 10477373803))
    panel._my_system_btn.click()
    assert len(made) == 1
    assert loads == [(10477373803, "Sol", "http://hub2")]
    panel.stop_finder_dialog()
    assert stops == [1]
