"""SessionActivityDialog._render_report() -- builds one card per system
(QFrame, _CARD_STYLE) with a color-coded, chip-style rich-text row per
faction, replacing the original plain-text dump. Real QApplication/
dialog, matching this app's own panel-smoke-test convention where a fake
self isn't practical for a QWidget method (see test_exploration_nearest_poi.py)."""
import sys
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
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1},
                "combat_bonds_total": 20000,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2},
                "trade_sold": {"commodity": 63085, "exploration": 0, "exobiology": 0},
            },
        },
        "Aiga": {
            "Hungarian Wolves": {
                "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0},
                "combat_bonds_total": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
            },
        },
    }
    dlg = _dialog()
    dlg._render_report(report)
    assert dlg._empty_label.isHidden() is True
    assert len(dlg._cards) == 2  # one per system


def test_faction_row_shows_color_coded_chips_only_for_actual_activity():
    entry = {
        "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1},
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
        "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0},
        "combat_bonds_total": 0,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
        "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
    }
    html = SessionActivityDialog._format_chips(entry)
    assert "no activity" in html


def test_rerender_clears_previous_cards():
    dlg = _dialog()
    report_a = {
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0},
                "combat_bonds_total": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
            },
        },
    }
    dlg._render_report(report_a)
    assert len(dlg._cards) == 1
    dlg._render_report({})
    assert dlg._cards == []
    assert dlg._empty_label.isHidden() is False
