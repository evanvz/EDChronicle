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


def _blocked(monkeypatch, gate):
    monkeypatch.setattr(mod, "fetch_colonisation_system",
                        lambda url, id64, faction=None: gate.wait(5) and TUC)


def _running(d):
    return [t for t, _ in d._threads if t.isRunning()]


def test_close_during_fetch_does_not_block(monkeypatch):
    import threading
    gate = threading.Event()
    _blocked(monkeypatch, gate)
    parent = QWidget()
    _keep.append(parent)
    d = mod.ColonisationDesignDialog(parent, "http://hub", 1, SYS)
    _keep.append(d)
    d.show()
    t0 = time.time()
    d.close()
    assert time.time() - t0 < 1
    gate.set()
    d.stop()
    assert not _running(d)


def test_late_result_for_previous_system_is_ignored(monkeypatch):
    import threading
    gate = threading.Event()
    _blocked(monkeypatch, gate)
    parent = QWidget()
    _keep.append(parent)
    d = mod.ColonisationDesignDialog(parent, "http://hub", 1, "A")
    _keep.append(d)
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: {"name": "B", "bodies": []})
    d.load(2, "B")
    deadline = time.time() + 5
    while d._system is None and time.time() < deadline:
        _app.processEvents()
    gate.set()
    d.stop()
    _app.processEvents()
    assert d.id64 == 2 and d._system["name"] == "B"


def test_finder_stop_leaves_no_running_thread_with_design_open(monkeypatch):
    import threading
    from tests.test_colonisation_finder_dialog import _dialog as fdialog, _search
    gate = threading.Event()
    _blocked(monkeypatch, gate)
    f = fdialog(monkeypatch)
    _search(f)
    f._table.selectRow(0)
    f._design_btn.click()
    d1 = f._design
    f._table.selectRow(1)
    f._design_btn.click()
    assert f._design is d1 and d1.id64 == f._table.item(1, 0).data(mod.Qt.ItemDataRole.UserRole)
    gate.set()
    f.stop()
    assert not _running(f._design) and not [t for t, _ in f._threads if t.isRunning()]


def test_nameless_body_gets_fallback_label_and_combo_enables(monkeypatch):
    s = {**TUC, "bodies": [dict(b, name=None) if b["body_id"] == 7 else b for b in TUC["bodies"]]}
    d = _dialog(monkeypatch, s)
    assert d._combo.isEnabled() and "Body 7" in [d._combo.itemText(i).strip() for i in range(d._combo.count())]
