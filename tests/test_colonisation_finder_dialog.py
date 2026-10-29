import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_finder_dialog as mod  # noqa: E402

ROWS = [
    {"id64": 1, "name": "Alpha", "distance_ly": 20.0, "to_squad_ly": 12.5, "score": 25, "port_types": ["Orbital"],
     "economies": ["HighTech"], "body_count": 4, "dump_date": "2026-10-20"},
    {"id64": 2, "name": "Beta", "distance_ly": 9.5, "to_squad_ly": None, "score": 5, "port_types": [],
     "economies": [], "body_count": 0, "dump_date": None},
]


def _dialog(monkeypatch, search_result=ROWS, calls=None):
    state = SimpleNamespace(system="Sol", system_x=0.0, system_y=0.0, system_z=0.0)
    panel = SimpleNamespace(_last_state=state, _repo=SimpleNamespace(db=SimpleNamespace(db_path=":memory:")))

    def fake_search(*args, **kw):
        if calls is not None:
            calls.append(args)
        return search_result

    monkeypatch.setattr(mod, "fetch_colonisation_search", fake_search)
    monkeypatch.setattr(mod, "_load_squad_ids", lambda db_path: [111, 222])
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64: None)
    monkeypatch.setattr(mod, "_spansh_claimed", lambda name: None)
    return mod.ColonisationFinderDialog(panel, "http://hub")


def _search(dlg):
    dlg._search_btn.click()
    deadline = time.time() + 5
    while not dlg._search_btn.isEnabled() and time.time() < deadline:
        _app.processEvents()
    _app.processEvents()
    dlg._threads["search"][0].wait()


def test_results_render_sorted_and_unknown_ports(monkeypatch):
    dlg = _dialog(monkeypatch)
    _search(dlg)
    t = dlg._table
    assert t.rowCount() == 2
    t.sortByColumn(1, mod.Qt.SortOrder.AscendingOrder)
    assert t.item(0, 0).text() == "Beta"
    assert t.item(0, 4).text() == "unknown"
    assert t.item(1, 4).text() == "Orbital"
    assert t.item(1, 7).text().endswith(" d")
    assert t.item(0, 7).text() == ""


def test_filter_box_hides_other_systems(monkeypatch):
    dlg = _dialog(monkeypatch)
    _search(dlg)
    dlg._filter.setText("alp")
    hidden = [dlg._table.item(r, 0).text() for r in range(2) if dlg._table.isRowHidden(r)]
    assert hidden == ["Beta"]


def test_hub_unreachable_shows_message_and_reenables_search(monkeypatch):
    dlg = _dialog(monkeypatch, search_result=None)
    _search(dlg)
    assert "EDDataHub not reachable" in dlg._status.text()
    assert dlg._search_btn.isEnabled()


def test_near_squad_sends_squad_ids(monkeypatch):
    calls = []
    dlg = _dialog(monkeypatch, calls=calls)
    dlg._near_chk.setChecked(True)
    _search(dlg)
    assert calls[0][7] == [111, 222]
    assert calls[0][8] == 30


def test_button_disabled_without_hub_url():
    from edc.ui.panels.colonisation_panel import ColonisationPanel
    panel = ColonisationPanel(MagicMock())
    assert not panel._find_btn.isEnabled()
    assert "Needs EDDataHub" in panel._find_btn.toolTip()
    panel.eddatahub_url = "http://hub"
    assert panel._find_btn.isEnabled()
