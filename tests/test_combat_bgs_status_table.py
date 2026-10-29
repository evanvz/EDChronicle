"""Combat > System Status table: filter by system name, sort by distance as a number (2026-10-29)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from edc.ui.panels.combat_bgs_status_panel import CombatBgsStatusPanel


def _row(name, dist):
    return {"system_name": name, "distance_ly": dist, "conflicts": [], "tiers": [], "data_timestamp": "",
            "faction_states": [{"name": "A", "active_states": [{"State": "Boom"}]}]}


def test_filter_by_system_and_sort_by_distance():
    app = QApplication.instance() or QApplication([])  # noqa: F841
    p = CombatBgsStatusPanel(repo=None)
    p._last_rows = [_row("Delta Indi", 9.5), _row("Ekono", 120.0), _row("Delta Pavonis", 30.0)]
    p._render_results()
    p._table.sortItems(1, Qt.SortOrder.AscendingOrder)
    assert [p._table.item(r, 0).text() for r in range(3)] == ["Delta Indi", "Delta Pavonis", "Ekono"]
    p._system_filter.setText("delta")
    assert sorted(p._table.item(r, 0).text() for r in range(p._table.rowCount())) == ["Delta Indi", "Delta Pavonis"]
