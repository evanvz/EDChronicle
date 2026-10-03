"""BgsTasksDialog -- add/remove/reorder tasks and render live progress
cards. Real QApplication + real temp-file Repository behind a fake panel,
matching test_session_activity_dialog_render.py's convention."""
import sys
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from edc.ui.panels.bgs_tasks_dialog import BgsTasksDialog
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_app = QApplication.instance() or QApplication(sys.argv)


def _dialog(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (12345, 'Ekono')")
    changed = []
    panel = SimpleNamespace(_repo=repo, _latest_known_tick=None, bgs_limits_getter=None,
                            bgs_tasks_changed=SimpleNamespace(emit=lambda: changed.append(1)))
    return BgsTasksDialog(panel), repo, changed


def _card_texts(dlg):
    return [" | ".join(l.text() for l in card.findChildren(QLabel)) for card in dlg._cards]


def test_add_boost_task_renders_a_card(tmp_path):
    dlg, repo, changed = _dialog(tmp_path)
    dlg._system_edit.setText("ekono")
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("boost"))
    dlg._faction_edit.setText("Elite United Worlds")
    dlg._on_add()
    assert dlg._form_error.text() == ""
    assert len(repo.list_bgs_tasks()) == 1
    assert len(dlg._cards) == 1
    text = _card_texts(dlg)[0]
    assert "Ekono — Boost Elite United Worlds" in text
    from PyQt6.QtWidgets import QProgressBar
    assert "0 / 25 INF" in [b.format() for b in dlg._cards[0].findChildren(QProgressBar)]
    assert "To do" in text
    assert dlg._system_edit.text() == ""  # form cleared
    assert changed == [1]


def test_card_shows_what_to_do_line(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "vote", faction_name="A", opponent_name="B")
    dlg.refresh()
    text = _card_texts(dlg)[0]
    assert "What to do:" in text
    assert "Election missions for A" in text  # short line
    guide = [l for l in dlg._cards[0].findChildren(QLabel) if "What to do:" in l.text()][0]
    assert "Complete election missions for A" in guide.toolTip()  # full guidance on hover


def test_cards_use_one_accent_colour_per_task_type(tmp_path):
    from edc.core.bgs_tasks import TYPE_COLORS

    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "vote", faction_name="A<b>", opponent_name="B")
    repo.add_bgs_task("Ekono", "fight", faction_name="C", opponent_name="D")
    dlg.refresh()
    for card, task_type in zip(dlg._cards, ("vote", "fight")):
        colour = TYPE_COLORS[task_type]
        assert colour in card.styleSheet()  # left border
        labels = card.findChildren(QLabel)
        assert colour in labels[0].styleSheet()  # title
        guide = [l for l in labels if "What to do" in l.text()][0]
        assert colour in guide.text()
    vote_guide = [l for l in dlg._cards[0].findChildren(QLabel) if "What to do" in l.text()][0]
    assert "A&lt;b&gt;" in vote_guide.text()  # faction names escaped in rich text


def test_invalid_input_shows_error_and_adds_nothing(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    dlg._system_edit.setText("Kanuket")
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("vote"))
    dlg._faction_edit.setText("Remnants of the Code")
    dlg._on_add()
    assert dlg._form_error.text() == "Enter the opposing faction."
    assert repo.list_bgs_tasks() == []


def test_unknown_system_card_says_not_seen_yet(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Kanuket", "vote", faction_name="A", opponent_name="B")
    dlg.refresh()
    assert "System not seen yet" in _card_texts(dlg)[0]


def test_remove_button_deletes_task(tmp_path):
    dlg, repo, changed = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "note", note="check in")
    dlg.refresh()
    remove = [b for b in dlg._cards[0].findChildren(QPushButton) if b.text() == "Remove"][0]
    remove.click()
    assert repo.list_bgs_tasks() == []
    assert dlg._cards == []
    assert changed == [1]


def test_move_down_button_reorders(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    a = repo.add_bgs_task("Ekono", "note", note="a")
    b = repo.add_bgs_task("Ekono", "note", note="b")
    dlg.refresh()
    down = [btn for btn in dlg._cards[0].findChildren(QPushButton) if btn.text() == "↓"][0]
    down.click()
    assert [t["id"] for t in repo.list_bgs_tasks()] == [b, a]


def test_opponent_field_only_enabled_for_vote_and_fight(tmp_path):
    dlg, _, _ = _dialog(tmp_path)
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("boost"))
    assert not dlg._opponent_edit.isEnabled()
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("fight"))
    assert dlg._opponent_edit.isEnabled()
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("note"))
    assert not dlg._faction_edit.isEnabled()


def test_done_card_gets_green_tint_and_met_line_is_green(tmp_path):
    from edc.core.bgs_tasks import DEFAULT_LIMITS

    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    repo.record_faction_bounty(12345, "Elite United Worlds", DEFAULT_LIMITS["bounties"], "2026-09-26T10:00:00Z")
    dlg.refresh()
    card = dlg._cards[0]
    assert "#0f2418" in card.styleSheet()
    from PyQt6.QtWidgets import QProgressBar
    bounty_bar = [b for b in card.findChildren(QProgressBar) if b.format().startswith("20.0M")][0]
    assert "rgba(107, 203, 119" in bounty_bar.styleSheet()  # met target = green (#6BCB77)


def test_unfinished_card_has_no_tint(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    dlg.refresh()
    assert "#0f2418" not in dlg._cards[0].styleSheet()
