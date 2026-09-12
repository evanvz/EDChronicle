"""CombatBgsStatusPanel._on_cell_clicked() -- clicking the System column
should copy the system name to the clipboard, matching the same
click-to-copy convention as intel_panel.py's nearby-farming table and
player_faction_panel.py's bucket dialogs. Confirmed missing entirely
from this panel. Patches QApplication.clipboard() rather than touching
the real OS clipboard (no existing test in this suite does real
clipboard I/O)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from edc.ui.panels.combat_bgs_status_panel import CombatBgsStatusPanel


def _fake_self(item_text):
    fake_item = SimpleNamespace(text=lambda: item_text)
    fake_table = MagicMock()
    fake_table.item.return_value = fake_item if item_text is not None else None
    return SimpleNamespace(_table=fake_table)


def test_clicking_system_column_copies_name():
    fake_self = _fake_self("Sol")
    fake_clipboard = MagicMock()
    with patch("edc.ui.panels.combat_bgs_status_panel.QApplication.clipboard", return_value=fake_clipboard):
        CombatBgsStatusPanel._on_cell_clicked(fake_self, 0, 0)
    fake_clipboard.setText.assert_called_once_with("Sol")


def test_clicking_other_column_does_not_copy():
    fake_self = _fake_self("Sol")
    fake_clipboard = MagicMock()
    with patch("edc.ui.panels.combat_bgs_status_panel.QApplication.clipboard", return_value=fake_clipboard):
        CombatBgsStatusPanel._on_cell_clicked(fake_self, 0, 1)
    fake_clipboard.setText.assert_not_called()


def test_clicking_empty_cell_does_not_copy():
    fake_self = _fake_self(None)
    fake_clipboard = MagicMock()
    with patch("edc.ui.panels.combat_bgs_status_panel.QApplication.clipboard", return_value=fake_clipboard):
        CombatBgsStatusPanel._on_cell_clicked(fake_self, 0, 0)
    fake_clipboard.setText.assert_not_called()
