"""Forecast tab: renders watched systems, cached candidates and the last
result without starting a lookup when the cache is fresh."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

EUW = "Elite United Worlds"


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _table_texts(table):
    return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_forecast_tab_renders_from_fresh_cache(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Ekono'), (2, 'Arimavante')")
    repo.save_faction_snapshot(1, {"Name": EUW, "Influence": 0.80}, today, True, f"{today}T12:00:00Z", "edsm")
    # EUW left Arimavante 20 days ago (older than the 14-day "current" window,
    # inside the 30-day pruning window so the test data isn't deleted on save)
    left = (date.today() - timedelta(days=20)).isoformat()
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.30}, left, False, f"{left}T00:00:00Z", "edsm")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo.save_expansion_candidates(1, [
        {"system_name": "Arimavante", "system_address": 2, "distance_ly": 10.9, "faction_count": 6, "faction_present": False},
        {"system_name": "Tucanae Sector YF-W b2-2", "system_address": 3, "distance_ly": 28.2, "faction_count": 4,
         "faction_present": False},
        {"system_name": "Unlooked", "system_address": 4, "distance_ly": 12.0, "faction_count": None,
         "faction_present": False}], now)
    panel = SimpleNamespace(_repo=repo, _faction_name=EUW)
    w = ExpansionForecastPanel(panel)
    w.refresh()
    assert w._thread is None                       # fresh cache -> no lookup started
    assert _table_texts(w._next_table)[0][0] == "Ekono"
    rows = _table_texts(w._target_table)
    # Arimavante: EUW was there before (left) -> tier 2, so YF-W ranks first
    assert [r[2] for r in rows] == ["Tucanae Sector YF-W b2-2", "Arimavante", "Unlooked"]
    assert rows[1][1] == "2" and rows[1][5] == "yes" and rows[2][1] == "not checked"


def test_no_faction_and_no_watched_system(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    repo = _repo(tmp_path)
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=None))
    w.refresh()
    assert "No squadron faction known yet" in w._status.text() and w._thread is None
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Low')")
    repo.save_faction_snapshot(1, {"Name": EUW, "Influence": 0.40}, today, True, f"{today}T12:00:00Z", "edsm")
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=EUW))
    w.refresh()
    assert "No faction system at 70% or more" in w._target_status.text() and w._thread is None


def test_worker_result_marks_failed_lookups_not_checked(tmp_path, monkeypatch):
    from edc.ui.panels import expansion_forecast_panel as fp
    repo = _repo(tmp_path)
    for name, xyz, pop in (("Near", (1.0, 0.0, 0.0), 100), ("Far", (15.0, 0.0, 0.0), 100),
                           ("Unknown pop", (2.0, 0.0, 0.0), None), ("Empty", (3.0, 0.0, 0.0), 0)):
        repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", (name, *xyz))
        if pop is not None:
            repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                            "VALUES (abs(random()) % 100000, ?, ?)", (name, pop))
    answers = {"Near": ({"system_address": 9, "factions": [{"Name": "A", "Influence": 0.5},
                                                            {"Name": EUW, "Influence": 0.1}]}, None),
               "Far": (None, "blocked")}
    monkeypatch.setattr(fp, "fetch_system_factions", lambda n: answers[n])
    out = []
    worker = fp._ForecastWorker(repo.db.db_path, {"x": 0.0, "y": 0.0, "z": 0.0}, set(), EUW)
    worker.finished.connect(lambda res, err: out.append((res, err)))
    worker.run()
    res, err = out[0]
    assert err is None and res["unknown_population"] == 1 and res["candidates"] == 2
    by = {r["system_name"]: r for r in res["rows"]}
    assert by["Near"]["faction_count"] == 2 and by["Near"]["faction_present"] is True
    assert by["Far"]["faction_count"] is None


def test_lookup_finished_after_source_changed_still_saves(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    repo = _repo(tmp_path)
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=EUW))
    w._source = None
    w._lookup_source = (1, "Ekono")
    rows = [{"system_name": "X", "system_address": 5, "distance_ly": 3.0, "faction_count": 4, "faction_present": False}]
    w._on_lookup_finished({"rows": rows, "candidates": 1, "unknown_population": 0}, None)
    assert [c["system_name"] for c in repo.get_expansion_candidates(1)] == ["X"]


def test_overview_alert_label():
    QApplication.instance() or QApplication([])
    from edc.ui.panels.overview_panel import OverviewPanel
    ov = OverviewPanel()
    ov.set_new_system_alert("🆕 EUW entered <b>X</b> (9.1%)")
    assert ov.new_system_badge.text() == "🆕 EUW entered <b>X</b> (9.1%)" and not ov.new_system_badge.isHidden()
    ov.set_new_system_alert("")
    assert ov.new_system_badge.isHidden()


def test_main_window_alert_uses_detection(tmp_path):
    from edc.ui.main_window import MainWindow
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'Tucanae Sector YF-W b2-2')")
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.091}, today, False, f"{today}T16:59:55Z", "eddn")
    shown = []
    fake = SimpleNamespace(repo=repo, overview_panel=SimpleNamespace(set_new_system_alert=shown.append),
                           player_faction_panel=SimpleNamespace(_faction_name=EUW))
    MainWindow._refresh_new_system_alert(fake)
    assert shown == ["🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%)"]
    fake.player_faction_panel._faction_name = None
    MainWindow._refresh_new_system_alert(fake)
    assert shown[-1] == ""


def test_session_report_shows_new_system_escaped(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'A <i>b</i>')")
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.05}, today, False, f"{today}T10:00:00Z", "eddn")
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name=EUW, _latest_known_tick=None))
    dlg.refresh()
    assert "A &lt;i&gt;b&lt;/i&gt;" in dlg._new_label.text() and not dlg._new_label.isHidden()
