"""Settings "PowerPlay allies" field shows the allies in effect for the
current pledge, and only a real edit turns it into a custom list."""
import sys
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit

from edc.ui.main_window import MainWindow

_app = QApplication.instance() or QApplication(sys.argv)


def _fake(pledged, configured=None):
    win = SimpleNamespace(
        state=SimpleNamespace(pp_power=pledged),
        cfg=SimpleNamespace(pp_allied_powers=configured),
        cfg_store=SimpleNamespace(save=lambda cfg: None),
        engine=SimpleNamespace(allied_powers_config=configured),
        allied_powers_edit=QLineEdit(),
        allied_powers_mode_label=QLabel(),
        _allies_edit_dirty=False,
    )
    win._refresh_allies_field = lambda: MainWindow._refresh_allies_field(win)
    return win


def test_automatic_shows_the_other_zyada_powers_for_a_zyada_pledge():
    win = _fake("Aisling Duval")
    MainWindow._refresh_allies_field(win)
    assert win.allied_powers_edit.text() == "Zemina Torval, Yuri Grom, A. Lavigny-Duval, Denton Patreus"
    assert "automatic" in win.allied_powers_mode_label.text()


def test_automatic_shows_no_allies_outside_zyada():
    win = _fake("Zachary Hudson")
    MainWindow._refresh_allies_field(win)
    assert win.allied_powers_edit.text() == ""


def test_focus_out_without_typing_keeps_it_automatic():
    win = _fake("Aisling Duval")
    MainWindow._refresh_allies_field(win)
    MainWindow._on_allied_powers_edited(win)  # editingFinished with no textEdited
    assert win.cfg.pp_allied_powers is None


def test_real_edit_saves_a_custom_list_and_reset_restores_automatic():
    win = _fake("Aisling Duval")
    win.allied_powers_edit.setText("Li Yong-Rui")
    win._allies_edit_dirty = True
    MainWindow._on_allied_powers_edited(win)
    assert win.cfg.pp_allied_powers == ["Li Yong-Rui"]
    assert win.engine.allied_powers_config == ["Li Yong-Rui"]
    assert "custom" in win.allied_powers_mode_label.text()
    MainWindow._on_allied_powers_reset(win)
    assert win.cfg.pp_allied_powers is None
    assert "automatic" in win.allied_powers_mode_label.text()
