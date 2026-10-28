"""PowerPlay Status tab: the week chart for the current system (local readings
plus hub readings, never stored)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from edc.core.bgs_tasks import powerplay_week_start
from edc.ui.panels.powerplay_panel import PowerplayPanel
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(addr):
    return SimpleNamespace(system_address=addr, system="Ys", pp_power="Aisling Duval",
                           system_controlling_power="Aisling Duval", system_powerplay_state="Exploited",
                           system_powers=[], system_powerplay_conflict_progress={},
                           system_powerplay_reinforcement=10, system_powerplay_undermining=5,
                           system_powerplay_control_progress=0.3)


def record_two_readings(repo, addr):
    now = datetime.now(timezone.utc)
    repo.record_pp_control(addr, _z(now - timedelta(minutes=50)), "Exploited", 5, 2, 0.3, "journal")
    repo.record_pp_control(addr, _z(now - timedelta(minutes=10)), "Exploited", 10, 5, 0.3, "journal")


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pp_panel(qapp, tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return PowerplayPanel(repo=Repository(db))


def test_chart_hidden_without_readings_and_shown_with(qapp, pp_panel):
    state = _state(77)
    pp_panel.refresh(state)
    assert pp_panel.pp_week_chart.isHidden()
    record_two_readings(pp_panel._repo, 77)
    pp_panel.refresh(state)
    assert not pp_panel.pp_week_chart.isHidden()
    assert pp_panel.pp_week_chart.grab().width() > 0          # paints without error
    assert pp_panel.pp_week_chart.caption().startswith("2 reports this week · last ")


def test_late_hub_answer_for_old_system_is_ignored(qapp, pp_panel):
    record_two_readings(pp_panel._repo, 77)
    record_two_readings(pp_panel._repo, 88)
    pp_panel.refresh(_state(77))
    pp_panel.refresh(_state(88))
    local_readings_for_88 = pp_panel._repo.get_pp_control_since(88, powerplay_week_start())
    reading = {"observed_at": _z(datetime.now(timezone.utc)), "pp_state": "Exploited",
               "reinforcement": 99, "undermining": 99, "control": 0.5, "source": "hub"}
    pp_panel._on_pp_hub({77: [reading]})
    assert pp_panel._pp_week_for == 88 and pp_panel.pp_week_chart._readings == local_readings_for_88


def test_failing_week_read_hides_chart_and_refresh_continues(qapp, pp_panel, monkeypatch):
    record_two_readings(pp_panel._repo, 77)
    pp_panel.refresh(_state(77))

    def boom(*a):
        raise RuntimeError("db gone")
    monkeypatch.setattr(pp_panel._repo, "get_pp_control_since", boom)
    pp_panel.pp_summary.setText("")
    pp_panel.refresh(_state(77))
    assert pp_panel.pp_week_chart.isHidden()
    assert "System: Ys" in pp_panel.pp_summary.text()


def test_weekly_reset_starts_a_new_window_in_the_same_system(qapp, pp_panel, monkeypatch):
    import edc.ui.panels.powerplay_panel as ppm
    record_two_readings(pp_panel._repo, 77)
    pp_panel.refresh(_state(77))
    pp_panel._pp_hub = pp_panel._repo.get_pp_control_since(77, powerplay_week_start())
    asked = []
    monkeypatch.setattr(pp_panel._pp_fetch, "start", lambda url, ids, since: asked.append((ids, since)))
    new_start = _z(datetime.now(timezone.utc))
    monkeypatch.setattr(ppm, "powerplay_week_start", lambda *a: new_start)
    pp_panel.refresh(_state(77))
    assert pp_panel._pp_week_start == new_start and pp_panel._pp_hub == []
    assert asked == [([77], new_start)]
    assert pp_panel.pp_week_chart.isHidden()               # last week's readings are gone


def test_banner_uses_newest_reading_hub_first(qapp, pp_panel):
    """The journal state says R 10 from your visit; a newer EDDataHub report
    (R 7,872) replaces it and the banner names its source."""
    record_two_readings(pp_panel._repo, 77)
    pp_panel.refresh(_state(77))
    assert "10" in pp_panel.pp_conflict_banner.text() and "your visit" in pp_panel.pp_conflict_banner.text()
    hub = {"observed_at": _z(datetime.now(timezone.utc) - timedelta(minutes=1)), "pp_state": "Exploited",
           "reinforcement": 7872, "undermining": 8541, "control": 0.29, "source": "hub"}
    pp_panel._on_pp_hub({77: [hub]})
    text = pp_panel.pp_conflict_banner.text()
    assert "7,872" in text and "8,541" in text and "EDDataHub" in text


def test_banner_falls_back_to_state_without_readings(qapp, pp_panel):
    pp_panel.refresh(_state(77))
    text = pp_panel.pp_conflict_banner.text()
    assert "10" in text and "EDDataHub" not in text and "your visit" not in text
