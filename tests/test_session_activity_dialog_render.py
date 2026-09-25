"""SessionActivityDialog._render_report() -- builds one card per system
(QFrame, _CARD_STYLE) with a color-coded, chip-style rich-text row per
faction, replacing the original plain-text dump. Real QApplication/
dialog, matching this app's own panel-smoke-test convention where a fake
self isn't practical for a QWidget method (see test_exploration_nearest_poi.py)."""
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from edc.ui.panels.session_activity_dialog import SessionActivityDialog

_app = QApplication.instance() or QApplication(sys.argv)


def _dialog():
    return SessionActivityDialog(SimpleNamespace())


def test_empty_report_shows_the_empty_label_and_no_cards():
    dlg = _dialog()
    dlg._render_report({})
    assert dlg._empty_label.isHidden() is False
    assert dlg._cards == []


def test_report_builds_one_card_per_system():
    report = {
        "2026-09-25": {
            "Ekono": {
                "Elite United Worlds": {
                    "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1,
                                 "by_type": {"Courier": 2, "Massacre Conflict CivilWar": 1}},
                    "combat_bonds_total": 20000,
                    "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2},
                    "trade_sold": {"commodity": 63085, "exploration": 0, "exobiology": 0},
                },
            },
            "Aiga": {
                "Hungarian Wolves": {
                    "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0, "by_type": {}},
                    "combat_bonds_total": 0,
                    "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                    "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
                },
            },
        },
    }
    dlg = _dialog()
    dlg._render_report(report)
    assert dlg._empty_label.isHidden() is True
    assert len(dlg._cards) == 2  # one per system
    assert len(dlg._day_headers) == 1  # one day


def test_report_with_activity_on_two_days_builds_two_day_headers():
    single_system = {
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
                             "by_type": {"Courier": 1}},
                "combat_bonds_total": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
            },
        },
    }
    report = {"2026-09-24": single_system, "2026-09-25": single_system}
    dlg = _dialog()
    dlg._render_report(report)
    assert len(dlg._day_headers) == 2
    assert len(dlg._cards) == 2


def test_faction_row_shows_color_coded_chips_only_for_actual_activity():
    entry = {
        "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1, "by_type": {"Courier": 3}},
        "combat_bonds_total": 20000,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2},
        "trade_sold": {"commodity": 63085, "exploration": 0, "exobiology": 0},
    }
    html = SessionActivityDialog._format_chips(entry)
    assert ".INF" in html
    assert ".CBs" in html
    assert "20,000" in html
    assert ".CZs" in html
    assert "2xspaceh" in html
    assert ".Sold" in html
    assert "63,085" in html
    assert "exploration" not in html  # zero value, not shown
    assert "exobiology" not in html


def test_faction_row_with_no_activity_shows_placeholder():
    entry = {
        "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0, "by_type": {}},
        "combat_bonds_total": 0,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
        "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
    }
    html = SessionActivityDialog._format_chips(entry)
    assert "no activity" in html


def test_mission_type_breakdown_sorts_by_count_descending():
    entry = {
        "missions": {"count": 3, "weighted": 6, "primary_count": 3, "secondary_count": 0,
                     "by_type": {"Massacre Conflict CivilWar": 1, "Courier": 2}},
    }
    text = SessionActivityDialog._format_mission_types(entry)
    assert text == "Courier x2, Massacre Conflict CivilWar x1"


def test_mission_type_breakdown_includes_cr_reward_per_type():
    entry = {
        "missions": {
            "count": 3, "weighted": 6, "primary_count": 3, "secondary_count": 0,
            "by_type": {"Courier": 2, "Massacre Conflict CivilWar": 1},
            "reward_by_type": {"Courier": 48200, "Massacre Conflict CivilWar": 312000},
        },
    }
    text = SessionActivityDialog._format_mission_types(entry)
    assert text == "Courier x2 (48,200 CR), Massacre Conflict CivilWar x1 (312,000 CR)"


def test_mission_type_breakdown_omits_cr_when_reward_is_zero():
    entry = {
        "missions": {
            "count": 1, "weighted": 0, "primary_count": 1, "secondary_count": 0,
            "by_type": {"Courier": 1}, "reward_by_type": {"Courier": 0},
        },
    }
    text = SessionActivityDialog._format_mission_types(entry)
    assert text == "Courier x1"


def test_mission_type_breakdown_empty_when_no_missions():
    entry = {"missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0, "by_type": {}}}
    assert SessionActivityDialog._format_mission_types(entry) == ""


def test_rerender_clears_previous_cards_and_day_headers():
    dlg = _dialog()
    report_a = {
        "2026-09-25": {
            "Ekono": {
                "Elite United Worlds": {
                    "missions": {"count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
                                 "by_type": {"Courier": 1}},
                    "combat_bonds_total": 0,
                    "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                    "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
                },
            },
        },
    }
    dlg._render_report(report_a)
    assert len(dlg._cards) == 1
    assert len(dlg._day_headers) == 1
    dlg._render_report({})
    assert dlg._cards == []
    assert dlg._day_headers == []
    assert dlg._empty_label.isHidden() is False


def test_day_header_labels_today_yesterday_and_older():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    older = today - timedelta(days=5)
    assert SessionActivityDialog._format_day_header(today.isoformat()).startswith("Today — ")
    assert SessionActivityDialog._format_day_header(yesterday.isoformat()).startswith("Yesterday — ")
    older_label = SessionActivityDialog._format_day_header(older.isoformat())
    assert older_label.endswith(f"— {older.isoformat()}")
    assert "Today" not in older_label and "Yesterday" not in older_label


def test_day_sections_render_most_recent_day_first():
    single_system = {
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
                             "by_type": {"Courier": 1}},
                "combat_bonds_total": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
            },
        },
    }
    report = {"2026-09-23": single_system, "2026-09-25": single_system, "2026-09-24": single_system}
    dlg = _dialog()
    dlg._render_report(report)
    dates_in_headers = [h.text().split(" — ")[-1] for h in dlg._day_headers]
    assert dates_in_headers == ["2026-09-25", "2026-09-24", "2026-09-23"]
