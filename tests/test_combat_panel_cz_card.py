from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from edc.ui.panels.combat_panel import CombatPanel  # noqa: E402


def test_cz_table_fits_its_rows():
    p = CombatPanel(MagicMock())
    tally = {"space_l": 1}
    p._refresh_cz_card(SimpleNamespace(cz_kills={"A": tally}))
    one = p.cz_table.height()
    p._refresh_cz_card(SimpleNamespace(cz_kills={"A": tally, "B": tally}))
    row = p.cz_table.verticalHeader().defaultSectionSize()
    assert p.cz_table.height() - one == row
    assert one == p.cz_table.horizontalHeader().height() + row + 4
