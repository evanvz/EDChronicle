"""PowerPlay Watch List: the "U 24 h" column and the per-day table, from local
readings plus hub readings (EDDataHub, never stored)."""
from datetime import datetime, timedelta, timezone

import pytest
from PyQt6.QtWidgets import QApplication
from types import SimpleNamespace

from edc.ui.panels import powerplay_watch_panel as pww
from edc.ui.panels.powerplay_watch_panel import PowerPlayWatchPanel
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

YS = 77


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel_with_rows(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (?, 'Ys')", (YS,))
    now = datetime.now(timezone.utc)
    # holding: undermining flat, reinforcement ahead
    repo.record_pp_control(YS, _z(now - timedelta(hours=5)), "Stronghold", 5000, 4000, 0.3, "journal")
    repo.record_pp_control(YS, _z(now - timedelta(hours=1)), "Stronghold", 6000, 4000, 0.31, "journal")
    monkeypatch.setattr(pww, "pp_watch", lambda *a: {YS: "squad system"})
    monkeypatch.setattr(pww, "powerplay_week_start", lambda *a: _z(now - timedelta(days=3)))
    return SimpleNamespace(_repo=repo, eddatahub_url="", pledged_power_getter=lambda: "Aisling Duval",
                           edsm_powerplay=None, _latest_known_tick=None)


def test_watch_shows_24h_column_and_day_table(qapp, panel_with_rows):
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh()
    hdr = [w._table.horizontalHeaderItem(c).text() for c in range(w._table.columnCount())]
    assert "U 24 h" in hdr
    assert hdr.index("U 24 h") == hdr.index("Data") - 1
    assert w._day_table.isHidden()
    w._table.selectRow(0)
    assert not w._day_table.isHidden() and w._day_table.rowCount() >= 1


def test_day_table_hides_when_selected_row_filtered_away(qapp, panel_with_rows):
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh(); w._table.selectRow(0)
    w._only_attacked.setChecked(True)          # Ys is "holding": filtered out
    assert w._day_table.isHidden()


def test_hub_readings_merge_in(qapp, panel_with_rows):
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh()
    assert w._table.item(0, w._col("U 24 h")).text() == "—"
    hub = {"observed_at": _z(datetime.now(timezone.utc) - timedelta(hours=25)), "pp_state": "Stronghold",
           "reinforcement": 4000, "undermining": 3000, "control": 0.29, "source": "hub"}
    w._on_hub({YS: [hub]})
    assert w._table.item(0, w._col("U 24 h")).text() == "+1,000 ↑"


def test_fetch_with_no_hub_emits_empty(qapp):
    from edc.ui.pp_week_worker import HubPowerplayFetch
    f, got = HubPowerplayFetch(), []
    f.done.connect(got.append)
    f.start("", [YS], "2026-10-22T07:00:00Z")
    assert got == [{}]


def test_fetch_uses_fresh_cache(qapp, monkeypatch):
    from edc.ui import pp_week_worker as pw
    monkeypatch.setitem(pw._CACHE, YS, (pw.time.monotonic(), [{"x": 1}]))
    f, got = pw.HubPowerplayFetch(), []
    f.done.connect(got.append)
    f.start("http://hub", [YS], "2026-10-22T07:00:00Z")
    assert got == [{YS: [{"x": 1}]}]
