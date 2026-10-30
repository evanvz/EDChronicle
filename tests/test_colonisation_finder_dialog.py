import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_finder_dialog as mod  # noqa: E402

_keep = []  # fake panels must outlive their dialogs
ROWS = [
    {"id64": 1, "name": "Alpha", "distance_ly": 20.0, "to_squad_ly": 12.5, "score": 25, "port_types": ["Orbital"],
     "economies": ["HighTech"], "body_count": 4, "dump_date": "2026-10-20",
     "claim_from": {"name": "Ross 690", "ly": 4.21}},
    {"id64": 3, "name": "Gamma", "distance_ly": 30.0, "to_squad_ly": 6.0, "score": 1, "port_types": [],
     "economies": [], "body_count": 0, "dump_date": None, "claim_from": {"name": "Ross 690", "ly": 4.21},
     "claim_station": {"system": "Base", "station": "Dock A", "ly": 6.04}},
    {"id64": 2, "name": "Beta", "distance_ly": 9.5, "to_squad_ly": None, "score": 5, "port_types": [],
     "economies": [], "body_count": 0, "dump_date": None},
]


def _dialog(monkeypatch, search_result=ROWS, calls=None):
    state = SimpleNamespace(system="Sol", system_x=0.0, system_y=0.0, system_z=0.0)
    panel = QWidget()
    panel._last_state = state
    panel._repo = SimpleNamespace(db=SimpleNamespace(db_path=":memory:"))
    _keep.append(panel)

    def fake_search(*args, **kw):
        if calls is not None:
            calls.append(args)
        return search_result

    monkeypatch.setattr(mod, "fetch_colonisation_search", fake_search)
    monkeypatch.setattr(mod, "_load_squad_faction", lambda db_path: "Elite United Worlds")
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: None)
    monkeypatch.setattr(mod, "_spansh_claimed", lambda name: None)
    d = mod.ColonisationFinderDialog(panel, "http://hub")
    _keep.append(d)
    return d


def _search(dlg):
    dlg._search_btn.click()
    deadline = time.time() + 5
    while not dlg._search_btn.isEnabled() and time.time() < deadline:
        _app.processEvents()
    _app.processEvents()
    dlg.stop()


def test_results_render_sorted_and_unknown_ports(monkeypatch):
    dlg = _dialog(monkeypatch)
    _search(dlg)
    t = dlg._table
    assert t.rowCount() == 3
    t.sortByColumn(1, mod.Qt.SortOrder.AscendingOrder)
    assert t.item(0, 0).text() == "Beta"
    assert t.item(2, 8).text() == "Base / Dock A (6.0 ly)"
    assert t.item(0, 4).text() == "unknown"
    assert t.item(1, 4).text() == "Orbital"
    assert t.item(1, 7).text().endswith(" d")
    assert t.item(0, 7).text() == ""
    assert t.item(0, 8).text() == ""
    assert t.item(1, 8).text() == "Ross 690 (4.2 ly)"


def test_filter_box_hides_other_systems(monkeypatch):
    dlg = _dialog(monkeypatch)
    _search(dlg)
    dlg._filter.setText("alp")
    hidden = [dlg._table.item(r, 0).text() for r in range(3) if dlg._table.isRowHidden(r)]
    assert sorted(hidden) == ["Beta", "Gamma"]


def test_hub_unreachable_shows_message_and_reenables_search(monkeypatch):
    dlg = _dialog(monkeypatch, search_result=None)
    _search(dlg)
    assert "EDDataHub not reachable" in dlg._status.text()
    assert dlg._search_btn.isEnabled()


def test_near_squad_station_sends_faction_and_claim_range(monkeypatch):
    calls = []
    dlg = _dialog(monkeypatch, calls=calls)
    dlg._near_chk.setChecked(True)
    _search(dlg)
    assert calls[0][7] == "Elite United Worlds"
    assert calls[0][8] == 15


def test_button_disabled_without_hub_url():
    from edc.ui.panels.colonisation_panel import ColonisationPanel
    panel = ColonisationPanel(MagicMock())
    assert not panel._find_btn.isEnabled()
    assert "Needs EDDataHub" in panel._find_btn.toolTip()
    panel.eddatahub_url = "http://hub"
    assert panel._find_btn.isEnabled()


def test_second_detail_fetch_does_not_block(monkeypatch):
    import threading
    dlg = _dialog(monkeypatch)
    _search(dlg)
    gate = threading.Event()
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: gate.wait(5) and {})
    t0 = time.time()
    dlg._table.selectRow(0)
    dlg._table.selectRow(1)
    assert time.time() - t0 < 1
    gate.set()
    dlg.stop()


def test_near_squad_station_without_faction_says_so(monkeypatch):
    calls = []
    dlg = _dialog(monkeypatch, calls=calls)
    monkeypatch.setattr(mod, "_load_squad_faction", lambda db_path: None)
    dlg._near_chk.setChecked(True)
    _search(dlg)
    assert calls == [] and dlg._status.text() == "No squad faction known yet"


def test_new_search_clears_old_detail(monkeypatch):
    dlg = _dialog(monkeypatch)
    dlg._spansh.setText("Spansh: free")
    dlg._bodies.setRowCount(3)
    _search(dlg)
    assert dlg._spansh.text() == "" and dlg._bodies.rowCount() == 0


def test_detail_lists_where_to_claim_from(monkeypatch):
    dlg = _dialog(monkeypatch)
    dlg._detail_id = 7
    dlg._on_detail_done((7, {"bodies": [], "claim_from": [{"name": "A", "ly": 3.0}, {"name": "B", "ly": 9.84}]}, False))
    assert dlg._spansh.text() == "Spansh: free    Claim from: A (3.0 ly), B (9.8 ly)"


def test_detail_lists_squad_claim_stations_first(monkeypatch):
    dlg = _dialog(monkeypatch)
    dlg._detail_id = 7
    dlg._on_detail_done((7, {"bodies": [], "claim_from": [{"name": "A", "ly": 3.0}],
                             "claim_stations": [{"system": "Base", "station": "Dock A", "ly": 6.04}]}, None))
    assert dlg._spansh.text() == "Spansh: unknown    Squad claim stations: Base / Dock A (6.0 ly)    Claim from: A (3.0 ly)"
