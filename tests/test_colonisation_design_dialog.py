import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_design_dialog as mod  # noqa: E402
from tests.test_colonisation_design import SYS, TUC  # noqa: E402

_keep = []


def _dialog(monkeypatch, system=TUC):
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: system)
    parent = QWidget()
    _keep.append(parent)
    d = mod.ColonisationDesignDialog(parent, "http://hub", 1, SYS)
    _keep.append(d)
    deadline = time.time() + 5
    while not d._combo.isEnabled() and d._banner.text() == "Loading…" and time.time() < deadline:
        _app.processEvents()
    _app.processEvents()
    d.stop()
    return d


def _pick(d, body):
    d._combo.setCurrentIndex(d._combo.findData(body))


def _titles(d):
    return [d._table.item(r, 0).text() for r in range(d._table.rowCount())]


def test_picking_gas_giant_3_renders_steps_in_order(monkeypatch):
    d = _dialog(monkeypatch)
    assert d._combo.currentData() is None and d._table.rowCount() == 0
    _pick(d, f"{SYS} 3")
    assert _titles(d)[:2] == ["Primary: Coriolis", "Comms installation"]
    assert "High Tech Hub" in _titles(d)
    assert not d._banner.isVisibleTo(d)


def test_star_pick_shows_red_banner_and_no_steps(monkeypatch):
    d = _dialog(monkeypatch)
    _pick(d, SYS)
    assert d._banner.isVisibleTo(d) and d._banner.text().startswith("Poor pick: Primary slot on a star")
    assert "#ff6b6b" in d._banner.styleSheet()
    assert d._table.rowCount() == 0


def test_no_body_details_says_so(monkeypatch):
    d = _dialog(monkeypatch, {"name": SYS, "bodies": [{"name": f"{SYS} 3"}]})
    assert d._banner.isVisibleTo(d) and d._banner.text() == "Hub has no body details yet"
    _pick(d, f"{SYS} 3")
    assert d._banner.text() == "Hub has no body details yet" and d._table.rowCount() == 0


def test_solo_group_toggle_replans(monkeypatch):
    d = _dialog(monkeypatch)
    _pick(d, f"{SYS} 3")
    d._group.setChecked(True)
    assert _titles(d)[0] == "Primary: Ocellus" and "Comms installation" not in _titles(d)
    d._solo.setChecked(True)
    assert _titles(d)[0] == "Primary: Coriolis"


def test_combo_groups_cluster_root_before_moons(monkeypatch):
    d = _dialog(monkeypatch)
    names = [d._combo.itemData(i) for i in range(d._combo.count())]
    assert names.index(f"{SYS} 3") < names.index(f"{SYS} 3 a") < names.index(f"{SYS} 4")
    assert d._combo.itemText(names.index(f"{SYS} 3 a")).startswith("      ")


def test_hub_unreachable(monkeypatch):
    d = _dialog(monkeypatch, None)
    assert d._banner.text() == "EDDataHub not reachable" and not d._combo.isEnabled()
