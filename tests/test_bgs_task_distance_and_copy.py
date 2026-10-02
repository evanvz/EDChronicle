"""BGS Tasks cards: distance from your current system and click-to-copy
system name."""
import sys
from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QLabel

from edc.core.bgs_tasks import distance_text
from edc.core.event_engine import EventEngine
from edc.core.state import GameState

_app = QApplication.instance() or QApplication(sys.argv)


def test_distance_text_variants():
    assert distance_text((0, 0, 0), (30, 40, 0)) == "50.0 ly"
    assert distance_text((0, 0, 0), (30, 40, 0), jump_range=20.0) == "50.0 ly · ~3 jumps"
    assert distance_text((0, 0, 0), (3, 4, 0), jump_range=20.0) == "5.0 ly · ~1 jump"
    assert distance_text((0, 0, 0), None) == "— ly"
    assert distance_text(None, (1, 1, 1)) == "— ly"
    assert distance_text((0, 0, 0), (0, 0, 0), same_system=True) == "here"


def test_loadout_records_max_jump_range(tmp_path):
    eng = EventEngine(GameState(), tmp_path)
    state, _ = eng.process({"event": "Loadout", "timestamp": "2026-10-02T10:00:00Z", "Ship": "cutter",
                            "ShipID": 3, "MaxJumpRange": 31.82, "Modules": []})
    assert state.ship_max_jump_range == 31.82


def test_clicking_the_title_copies_the_system_name():
    from edc.ui.panels.bgs_tasks_dialog import BgsTasksDialog
    fake = SimpleNamespace(_distance_by_task={}, _copy_system=lambda lbl, name: BgsTasksDialog._copy_system(fake, lbl, name))
    view = {"task": {"id": 1, "system_name": "Ekono", "task_type": "boost", "faction_name": "EUW",
                     "opponent_name": None, "note": None, "system_address": 1, "pp_mode": None},
            "status": "", "lines": [], "warnings": [], "guide": ""}
    card = BgsTasksDialog._make_card(fake, view)
    title = card.findChildren(QLabel)[0]
    assert title.text().startswith("Ekono")
    QApplication.clipboard().setText("")
    title.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
                                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                      Qt.KeyboardModifier.NoModifier))
    assert QApplication.clipboard().text() == "Ekono"
