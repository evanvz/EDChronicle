"""Forecast tab: renders watched systems, cached candidates and the last
result without starting a lookup when the cache is fresh."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

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
    # Within throttle window, should resend cached text
    MainWindow._refresh_new_system_alert(fake)
    assert shown[-1] == "🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%)"


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


def test_refresh_new_system_alert_throttles_detection(tmp_path, monkeypatch):
    from edc.ui.main_window import MainWindow
    import edc.ui.main_window
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'Test System')")
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.091}, today, False, f"{today}T16:59:55Z", "eddn")

    call_count = [0]
    original_detect = edc.ui.main_window.detect_new_systems
    def counting_detect(r, f):
        call_count[0] += 1
        return original_detect(r, f)
    monkeypatch.setattr(edc.ui.main_window, "detect_new_systems", counting_detect)

    shown = []
    fake = SimpleNamespace(
        repo=repo,
        overview_panel=SimpleNamespace(set_new_system_alert=shown.append),
        player_faction_panel=SimpleNamespace(_faction_name=EUW)
    )

    # First call should detect
    MainWindow._refresh_new_system_alert(fake)
    assert call_count[0] == 1
    first_text = shown[-1]

    # Second call within throttle should NOT detect again
    MainWindow._refresh_new_system_alert(fake)
    assert call_count[0] == 1  # Still 1, not incremented
    assert shown[-1] == first_text  # Same text resent

    # Call with force=True should detect again
    MainWindow._refresh_new_system_alert(fake, force=True)
    assert call_count[0] == 2  # Now incremented


def test_refresh_new_system_alert_fallback_to_squadron_faction(tmp_path):
    from edc.ui.main_window import MainWindow
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'Fallback Test')")
    # Save snapshot with SquadronFaction=True to mark EUW as the squadron faction
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.075, "SquadronFaction": True}, today, False, f"{today}T14:00:00Z", "eddn")

    shown = []
    fake = SimpleNamespace(
        repo=repo,
        overview_panel=SimpleNamespace(set_new_system_alert=shown.append),
        player_faction_panel=SimpleNamespace(_faction_name=None)  # No explicit faction
    )

    MainWindow._refresh_new_system_alert(fake, force=True)
    # Should have fallen back and found the squadron faction
    assert shown[-1] != ""  # Should have found and displayed the new system
    assert "Elite United Worlds" in shown[-1]  # EUW should be in the text


def _cache_row(repo, count=6):
    repo.save_expansion_candidates(1, [
        {"system_name": "A", "system_address": 2, "distance_ly": 5.0, "faction_count": count, "faction_present": True},
        {"system_name": "B", "system_address": 3, "distance_ly": 6.0, "faction_count": 4, "faction_present": False}],
        "2026-10-01T10:00:00Z")


def _panel_with_source(repo):
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    QApplication.instance() or QApplication([])
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=EUW))
    w._source = {"system_address": 1, "system_name": "Ekono", "eligible": True}
    w._lookup_source = (1, "Ekono")
    return w


def _failed(name, addr, d):
    return {"system_name": name, "system_address": addr, "distance_ly": d, "faction_count": None,
            "faction_present": False}


def test_all_lookups_failed_keeps_old_cache(tmp_path):
    repo = _repo(tmp_path)
    _cache_row(repo)
    w = _panel_with_source(repo)
    w._on_lookup_finished({"rows": [_failed("A", 2, 5.0), _failed("B", 3, 6.0)], "candidates": 2,
                           "unknown_population": 0, "failed": 2}, None)
    cached = repo.get_expansion_candidates(1)
    assert [c["faction_count"] for c in cached] == [6, 4]
    assert {c["fetched_at"] for c in cached} == {"2026-10-01T10:00:00Z"}
    assert w._target_status.text().startswith("Lookup failed")
    assert "2026-10-01 10:00" in w._target_status.text()


def test_all_lookups_failed_without_cache(tmp_path):
    repo = _repo(tmp_path)
    w = _panel_with_source(repo)
    w._on_lookup_finished({"rows": [_failed("A", 2, 5.0)], "candidates": 1, "unknown_population": 0, "failed": 1}, None)
    assert repo.get_expansion_candidates(1) == []
    assert w._target_status.text().startswith("Lookup failed")


def test_partial_failure_keeps_old_count_and_saves(tmp_path):
    repo = _repo(tmp_path)
    _cache_row(repo)
    w = _panel_with_source(repo)
    ok = {"system_name": "A", "system_address": 2, "distance_ly": 5.0, "faction_count": 3, "faction_present": False}
    w._on_lookup_finished({"rows": [ok, _failed("B", 3, 6.0)], "candidates": 5, "unknown_population": 0,
                           "failed": 1}, None)
    by = {c["system_name"]: c for c in repo.get_expansion_candidates(1)}
    assert by["A"]["faction_count"] == 3
    assert by["B"]["faction_count"] == 4 and by["B"]["faction_present"] is False
    assert by["B"]["fetched_at"] != "2026-10-01T10:00:00Z"
    assert "Looked up 2 of 5" in w._target_status.text()


def test_empty_cube_message(tmp_path):
    repo = _repo(tmp_path)
    w = _panel_with_source(repo)
    w._on_lookup_finished({"rows": [], "candidates": 0, "unknown_population": 0, "failed": 0}, None)
    assert "No populated system without the faction within" in w._target_status.text()


def test_worker_cancel_stops_before_lookups(tmp_path, monkeypatch):
    from edc.ui.panels import expansion_forecast_panel as fp
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES ('Near', 1.0, 0.0, 0.0)")
    repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                    "VALUES (7, 'Near', 100)")
    calls = []
    monkeypatch.setattr(fp, "fetch_system_factions", lambda n: calls.append(n) or (None, "x"))
    out = []
    worker = fp._ForecastWorker(repo.db.db_path, {"x": 0.0, "y": 0.0, "z": 0.0}, set(), EUW)
    worker.finished.connect(lambda res, err: out.append((res, err)))
    worker.cancel()
    worker.run()
    assert calls == [] and out == [(None, "cancelled")]


def test_worker_counts_failed(tmp_path, monkeypatch):
    from edc.ui.panels import expansion_forecast_panel as fp
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES ('Near', 1.0, 0.0, 0.0)")
    repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                    "VALUES (7, 'Near', 100)")
    monkeypatch.setattr(fp, "fetch_system_factions", lambda n: (None, "blocked"))
    out = []
    worker = fp._ForecastWorker(repo.db.db_path, {"x": 0.0, "y": 0.0, "z": 0.0}, set(), EUW)
    worker.finished.connect(lambda res, err: out.append(res))
    worker.run()
    assert out[0]["failed"] == 1


def test_shutdown_sweep_reaches_forecast_panel():
    from PyQt6.QtCore import QObject, QThread
    from edc.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])

    class W(QObject):
        cancelled = False

        def cancel(self):
            self.cancelled = True

    t, wk = QThread(), W()
    t.start()
    forecast = SimpleNamespace(_thread=t, _worker=wk)
    fake = SimpleNamespace(player_faction_panel=SimpleNamespace(
        _faction_expansion_dialog=SimpleNamespace(_forecast=forecast)))
    MainWindow._stop_background_threads(fake, fake)
    assert wk.cancelled and not t.isRunning()
