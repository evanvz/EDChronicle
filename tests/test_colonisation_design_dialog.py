import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels import colonisation_design_dialog as mod  # noqa: E402
from tests.test_colonisation_design import SYS, TUC  # noqa: E402

_keep = []


def _dialog(monkeypatch, system=TUC, raven=None):
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: system)
    monkeypatch.setattr(mod, "get_system_slots", lambda name: raven)
    parent = QWidget()
    _keep.append(parent)
    d = mod.ColonisationDesignDialog(parent, "http://hub", 1, SYS)
    _keep.append(d)
    deadline = time.time() + 5
    while not d._combo.isEnabled() and d._banner.text() == "Loading…" and time.time() < deadline:
        _app.processEvents()
    _app.processEvents()
    d.stop()
    _app.processEvents()  # the Raven Colonial slots result
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


def test_weak_pick_shows_amber_banner_with_steps(monkeypatch):
    from tests.test_colonisation_design import _in_s_like
    d = _dialog(monkeypatch, _in_s_like())
    _pick(d, f"{SYS} 1")
    assert d._banner.isVisibleTo(d) and d._banner.text().startswith("Usable, but a weak pick: 1,686 ls out")
    assert "hub service score 16 (middle)" in d._banner.text() and "#ff6b6b" not in d._banner.styleSheet()
    assert _titles(d)[0] == "Primary: Coriolis"


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
    monkeypatch.setattr(mod, "get_system_slots", lambda name: None)


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


def _wait_saved(d):
    deadline = time.time() + 5
    while d._mark_lbl.text() == "Saving…" and time.time() < deadline:
        _app.processEvents()
    d.stop()


def test_mark_bad_sends_primary_body_note_and_cmdr(monkeypatch):
    sent, marked = [], []
    monkeypatch.setattr(mod, "put_colonisation_mark", lambda *a: sent.append(a) or True)
    d = _dialog(monkeypatch, {**TUC})
    d.parent()._panel = SimpleNamespace(_last_state=SimpleNamespace(commander="Evan"))
    d.on_marked = lambda id64, mark: marked.append((id64, mark))
    d._mark_btns["bad"].click()
    assert not sent and d._mark_lbl.text().startswith("Pick the primary slot body first")
    _pick(d, f"{SYS} 1")                                     # planet without moons: poor pick, bad button highlighted
    assert "#ff6b6b" in d._mark_btns["bad"].styleSheet()
    d._note.setText(" no moons ")
    d._mark_btns["bad"].click()
    _wait_saved(d)
    assert sent == [("http://hub", 1, "bad", f"{SYS} 1", "no moons", "Evan")]
    assert marked[0][0] == 1 and marked[0][1]["verdict"] == "bad"
    assert d._mark_lbl.text() == f"Marked bad by Evan, primary {SYS} 1: no moons"


def test_clear_mark_sends_nulls_and_hub_refusal_says_so(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_mark", lambda *a: sent.append(a) or False)
    d = _dialog(monkeypatch, {**TUC})
    d._mark_btns[None].click()
    _wait_saved(d)
    assert sent == [("http://hub", 1, None, None, None, None)]
    assert d._mark_lbl.text().startswith("Hub did not store the mark")


def test_existing_mark_shows_and_preselects_primary(monkeypatch):
    d = _dialog(monkeypatch, {**TUC, "mark": {"verdict": "good", "primary_body": f"{SYS} 3", "note": "ok", "cmdr": "Evan",
                                              "marked_at": "2026-10-31T10:00:00+00:00"}})
    assert d._combo.currentData() == f"{SYS} 3" and d._table.rowCount() > 0
    assert d._note.text() == "ok" and d._mark_lbl.text() == f"Marked good by Evan 2026-10-31, primary {SYS} 3: ok"


def _kind(d, kind):
    d._kind.setCurrentIndex(d._kind.findData(kind))


def _slotted():
    """TUC with squad-entered slots on gas giant 3 and its moons, the rest unknown."""
    entered = {7: (3, 0), 9: (1, 2), 12: (1, 3), 15: (1, 3), 10: (0, 1)}
    return {**TUC, "bodies": [dict(b, orbital_slots=entered[b["body_id"]][0], surface_slots=entered[b["body_id"]][1])
                              if b["body_id"] in entered else dict(b) for b in TUC["bodies"]]}


def _all_slotted():
    """_slotted with every other body entered too: 0 orbital, its estimate on the surface."""
    return {**_slotted(), "bodies": [b if "orbital_slots" in b else dict(b, orbital_slots=0, surface_slots=b.get("ground_slots") or 0)
                                     for b in _slotted()["bodies"]]}


def test_type_selector_lists_types(monkeypatch):
    from edc.core.colonisation_planner import TYPES, TYPE_NAMES
    d = _dialog(monkeypatch)
    assert [d._kind.itemText(i) for i in range(d._kind.count())] == ["Template"] + [TYPE_NAMES[t] for t in TYPES]
    assert d._kind.currentText() == "Template" and d._kind.currentData() is None


def test_slot_grid_shows_sources(monkeypatch):
    s = _slotted()
    d = _dialog(monkeypatch, s, raven={f"{SYS} 1": (2, None)})
    g = d._slots
    assert g.rowCount() == len(s["bodies"])
    rows = {g.item(r, 0).text(): [g.item(r, c).text() for c in (1, 2, 3)] for r in range(g.rowCount())}
    assert rows["3"] == ["3", "0", "entered / entered"]
    assert rows["1"] == ["2", "", "Raven / est. 0"]
    assert rows["2"] == ["", "", "? / est. 0"]
    assert not g.item(0, 3).flags() & mod.Qt.ItemFlag.ItemIsEditable and g.item(0, 1).flags() & mod.Qt.ItemFlag.ItemIsEditable


def test_full_build_renders_plan_and_outcome(monkeypatch):
    from edc.core.colonisation_planner import plan, slot_table
    s = _all_slotted()
    d = _dialog(monkeypatch, s)
    _pick(d, f"{SYS} 3")
    _kind(d, "full")
    p = plan(s, slot_table(s, None), f"{SYS} 3", False, "full")
    assert p["steps"] and _titles(d) == [st["title"] for st in p["steps"]]
    assert _titles(d)[0] == "Primary: Coriolis" and d._table.item(0, 2).text() == "free"
    assert d._table.item(0, 4).text() == f"T2 {p['steps'][0]['t2']}, T3 {p['steps'][0]['t3']}; 63,001 t"
    text = d._outcome.text()
    assert "score" in text and "haul" in text and "sec" in text and d._outcome.isVisibleTo(d)
    assert "Up to 5 facilities can be under construction at once" in d._warnings.text()
    _kind(d, None)
    assert _titles(d)[:2] == ["Primary: Coriolis", "Comms installation"] and not d._outcome.text()


def _wait_slots(d):
    deadline = time.time() + 5
    while d._slots_lbl.text() == "Saving…" and time.time() < deadline:
        _app.processEvents()
    d.stop()
    _app.processEvents()


def test_save_slots_puts_each_changed_body(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: sent.append(a) or True)
    d = _dialog(monkeypatch, _slotted())
    d.parent()._panel = SimpleNamespace(_last_state=SimpleNamespace(commander="Evan"))
    r = next(r for r in range(d._slots.rowCount()) if d._slots.item(r, 0).text() == "4")
    d._slots.item(r, 1).setText("2")
    d._save_slots_btn.click()
    assert d._slots.editTriggers() == mod.QTableWidget.EditTrigger.NoEditTriggers   # locked while saving
    _wait_slots(d)
    assert d._slots.editTriggers() == d._edit_triggers
    assert sent == [("http://hub", 1, 28, 2, None, "Evan")]
    assert d._slots.item(r, 3).text() == "entered / est. 0"
    d._save_slots_btn.click()
    assert len(sent) == 1


def test_no_slots_falls_back_to_template(monkeypatch):
    s = {**TUC, "bodies": [dict(b, ground_slots=None) for b in TUC["bodies"]]}
    d = _dialog(monkeypatch, s)
    _pick(d, f"{SYS} 3")
    _kind(d, "full")
    assert _titles(d) == [st["title"] for st in mod.plan_system(s, f"{SYS} 3", False)["steps"]]
    n = len(s["bodies"])
    assert f"{n} of {n} bodies not confirmed" in d._warnings.text() and not d._outcome.text()


def test_typed_plan_waits_for_every_slot_confirmed(monkeypatch):
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: True)
    s = _slotted()
    d = _dialog(monkeypatch, s, raven={f"{SYS} 1": (2, 0)})
    _pick(d, f"{SYS} 3")
    _kind(d, "full")
    g = d._slots
    open_ = sum(1 for b in s["bodies"] if "orbital_slots" not in b)
    assert _titles(d) == [st["title"] for st in mod.plan_system(s, f"{SYS} 3", False)["steps"]] and not d._outcome.text()
    assert (f"Check every body's slots in Architect View, then Confirm and save slots to plan by type: "
            f"{open_} of {len(s['bodies'])} bodies not confirmed") in d._warnings.text()
    for r in range(g.rowCount()):
        for c in (1, 2):
            if not g.item(r, c).text():
                g.item(r, c).setText("0")
    assert not d._outcome.text() and f"{open_} of" in d._warnings.text()   # filled is not confirmed: Raven row too
    d._save_slots_btn.click()
    _wait_slots(d)
    assert d._outcome.text() and "not confirmed" not in d._warnings.text()


def _row(d, label):
    return next(r for r in range(d._slots.rowCount()) if d._slots.item(r, 0).text() == label)


def test_raven_refill_keeps_earlier_edit(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: sent.append(a) or True)
    d = _dialog(monkeypatch, _slotted())
    d._slots.item(_row(d, "4"), 1).setText("2")
    d._on_raven((1, {f"{SYS} 1": (2, None), f"{SYS} 4": (5, None)}))
    assert d._slots.item(_row(d, "1"), 3).text() == "Raven / est. 0"
    assert d._slots.item(_row(d, "4"), 1).text() == "2" and d._slots.item(_row(d, "4"), 3).text() == "Raven / est. 0"
    d._save_slots_btn.click()
    _wait_slots(d)
    assert sorted(sent) == [("http://hub", 1, 5, 2, None, None), ("http://hub", 1, 28, 2, None, None)]


def test_save_confirms_raven_not_estimates(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: sent.append(a) or True)
    d = _dialog(monkeypatch, _slotted(), raven={f"{SYS} 1": (2, 4)})
    d._slots.item(_row(d, "4"), 1).setText("2")      # surface est.
    d._slots.item(_row(d, "1"), 2).setText("3")      # orbital Raven
    d._slots.item(_row(d, "3 a"), 1).setText("2")    # surface entered
    d._save_slots_btn.click()
    _wait_slots(d)
    assert sorted(sent) == sorted([("http://hub", 1, 28, 2, None, None), ("http://hub", 1, 5, 2, 3, None),
                                   ("http://hub", 1, 9, 2, 2, None)])


def test_partial_save_retry_keeps_estimates_out(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: sent.append(a) or a[2] == 28)
    d = _dialog(monkeypatch, _slotted())
    d._slots.item(_row(d, "4"), 1).setText("2")      # surface est., stored
    d._slots.item(_row(d, "3 a"), 1).setText("2")    # refused
    d._save_slots_btn.click()
    _wait_slots(d)
    sent.clear()
    d._save_slots_btn.click()
    _wait_slots(d)
    assert sent == [("http://hub", 1, 9, 2, 2, None)]
    assert d._slots.item(_row(d, "3 a"), 1).text() == "2" and d._slots.item(_row(d, "4"), 3).text() == "entered / est. 0"


def test_estimate_is_a_hint_not_a_count(monkeypatch):
    s = _slotted()
    d = _dialog(monkeypatch, s)
    b = next(b for b in s["bodies"] if b.get("landable") and "surface_slots" not in b and b.get("ground_slots"))
    r = _row(d, b["name"].removeprefix(SYS).strip())
    assert d._slots.item(r, 2).text() == "" and d._slots.item(r, 3).text().endswith(f"/ est. {b['ground_slots']}")


def test_slot_grid_reverts_bad_input(monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: sent.append(a) or True)
    d = _dialog(monkeypatch, _slotted())
    r = _row(d, "3 a")
    d._slots.item(r, 1).setText("5")
    for bad in ("x", "21", "-1", "1.5"):
        d._slots.item(r, 1).setText(bad)
        assert d._slots.item(r, 1).text() == "5"
    d._slots.item(r, 2).setText("oops")
    assert d._slots.item(r, 2).text() == "2"
    d._save_slots_btn.click()
    _wait_slots(d)
    assert sent == [("http://hub", 1, 9, 5, 2, None)]


def test_late_raven_result_for_previous_system_is_ignored(monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr(mod, "fetch_colonisation_system", lambda url, id64, faction=None: TUC)
    monkeypatch.setattr(mod, "get_system_slots",
                        lambda name: gate.wait(5) and ({f"{SYS} 1": (2, None)} if name == SYS else None))
    parent = QWidget()
    _keep.append(parent)
    d = mod.ColonisationDesignDialog(parent, "http://hub", 1, SYS)
    _keep.append(d)
    deadline = time.time() + 5
    while not d._combo.isEnabled() and time.time() < deadline:
        _app.processEvents()
    # system B has a body with the same name, so a misapplied result would show as "Raven"
    monkeypatch.setattr(mod, "fetch_colonisation_system",
                        lambda url, id64, faction=None: {"name": "B", "bodies": [{"name": f"{SYS} 1", "body_id": 5}]})
    d.load(2, "B")
    while (d._system is None or d._system["name"] != "B") and time.time() < deadline:
        _app.processEvents()
    gate.set()
    d.stop()
    _app.processEvents()
    assert d.id64 == 2 and d._raven is None and d._slots.item(0, 3).text() == "? / ?"


def test_save_refused_says_so_and_unlocks(monkeypatch):
    monkeypatch.setattr(mod, "put_colonisation_slots", lambda *a: False)
    d = _dialog(monkeypatch, _slotted())
    d._slots.item(_row(d, "4"), 1).setText("2")
    d._save_slots_btn.click()
    _wait_slots(d)
    assert d._slots_lbl.text().startswith("Hub did not store 1 of 1 bodies")
    assert d._save_slots_btn.isEnabled() and d._slots.editTriggers() == d._edit_triggers
    assert d._slots.item(_row(d, "4"), 1).text() == "2"


def test_save_worker_error_reenables(monkeypatch):
    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(mod, "put_colonisation_slots", boom)
    d = _dialog(monkeypatch, _slotted())
    d._slots.item(_row(d, "4"), 1).setText("2")
    d._save_slots_btn.click()
    _wait_slots(d)
    assert d._slots_lbl.text() == "Slots not saved (error, see the log)"
    assert d._save_slots_btn.isEnabled() and d._slots.editTriggers() == d._edit_triggers
