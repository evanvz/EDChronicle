"""UI-thread lag found in game on 2026-10-02 (profiled with py-spy): the HUD
refresh, run many times a second while the game writes Status.json, kept
re-running slow database lookups."""
import logging
import sys
import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from edc.ui.main_window import MainWindow, _UiStallWatchdog
from edc.ui.panels.squadron_panel import SquadronPanel

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


def test_squadron_panel_reads_the_faction_name_at_most_once_a_minute():
    calls = []
    repo = SimpleNamespace(get_squadron_faction_name=lambda: calls.append(1) or "Elite United Worlds")
    panel = SquadronPanel(repo)
    state = SimpleNamespace(squadron_name="EUW", squadron_rank=3, squadron_trophies=0, squadron_status=None,
                            squadron_status_timestamp=None, squadron_rank_history=[])
    for _ in range(10):
        panel.refresh(state)
    assert calls == [1]
    assert "Elite United Worlds" in panel._bgs_label.text()


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
