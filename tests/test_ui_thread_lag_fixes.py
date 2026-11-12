"""UI-thread lag found in game on 2026-10-02 (profiled with py-spy): the HUD
refresh, run many times a second while the game writes Status.json, kept
re-running slow database lookups."""
import logging
import sys
import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from edc.ui.main_window import MainWindow, _UiStallWatchdog

_app = QApplication.instance() or QApplication(sys.argv)


def test_fine_status_recomputes_only_when_system_or_fines_change():
    calls = []
    fake = SimpleNamespace(
        state=SimpleNamespace(active_fines={"A": 1000}, system_x=1.0, system_y=2.0, system_z=3.0,
                              system_address=1, closest_fine_stations={}),
        repo=SimpleNamespace(find_closest_station_for_faction=lambda x, y, z, f: calls.append(f) or {"station": f}),
    )
    for _ in range(5):
        MainWindow._refresh_fine_status(fake)
    assert calls == ["A"]
    fake.state.system_address = 2
    MainWindow._refresh_fine_status(fake)
    fake.state.active_fines = {"A": 1000, "B": 50}
    MainWindow._refresh_fine_status(fake)
    assert calls == ["A", "A", "A", "B"]


def test_watchdog_logs_where_the_ui_thread_is_stuck(caplog):
    caplog.set_level(logging.WARNING, logger="edc.ui.main")
    _UiStallWatchdog(None, describe=lambda: " (last journal event: LoadGame)")
    _app.processEvents()
    time.sleep(2.8)  # block the UI thread
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not any("recovered" in r.message for r in caplog.records):
        _app.processEvents()
        time.sleep(0.05)
    stuck = [r.message for r in caplog.records if "unresponsive" in r.message]
    assert stuck and "LoadGame" in stuck[0] and "test_watchdog_logs_where_the_ui_thread_is_stuck" in stuck[0]
    assert any("recovered after" in r.message for r in caplog.records)


def test_facilitator_candidates_worker_runs_off_the_ui_thread(tmp_path):
    from persistence.database import Database
    from persistence.schema import SCHEMA_SQL
    from edc.ui.main_window import _FacilitatorCandidatesWorker

    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    db.close()
    out = []
    worker = _FacilitatorCandidatesWorker(tmp_path / "t.db", frozenset({"Faction A"}))
    worker.finished.connect(lambda key, cands: out.append((key, cands)))
    worker.run()
    assert out == [(frozenset({"Faction A"}), [])]


def test_bulk_table_fill_restores_auto_columns_and_fills_fast():
    from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
    from edc.ui.style import bulk_table_fill

    table = QTableWidget(0, 3)
    h = table.horizontalHeader()
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    table.show()
    start = time.perf_counter()
    with bulk_table_fill(table):
        assert h.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
        table.setRowCount(2000)
        for r in range(2000):
            for c in range(3):
                table.setItem(r, c, QTableWidgetItem(f"Some Station Name {r} — {c}"))
    _app.processEvents()
    assert time.perf_counter() - start < 5  # was quadratic: minutes for ~2000 rows
    assert h.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert h.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents
    assert h.sectionResizeMode(2) == QHeaderView.ResizeMode.ResizeToContents


def test_bond_station_follows_the_cz_faction_and_looks_up_once_per_change():
    calls = []
    fake = SimpleNamespace(
        state=SimpleNamespace(cz_kills={"SMMI": {"space_l": 1}, "Idle": {"space_l": 0}}, system_x=1.0,
                              system_y=2.0, system_z=3.0, system_address=1, closest_squadron_station=None),
        repo=SimpleNamespace(find_closest_station_for_faction=lambda x, y, z, f, bonds=False:
                             calls.append((f, bonds)) or {"station_faction": f, "distance_ly": 4.0}),
    )
    for _ in range(5):
        MainWindow._refresh_squadron_station(fake)
    assert calls == [("SMMI", True)]
    assert fake.state.closest_squadron_station == {"station_faction": "SMMI", "distance_ly": 4.0}
    fake.state.cz_kills = {}
    MainWindow._refresh_squadron_station(fake)
    assert fake.state.closest_squadron_station is None
