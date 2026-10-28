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
