"""
Voice Commands settings panel.

Lets the user configure ship voice commands: add, edit, enable/disable,
and delete entries. Shows the resolved keyboard/controller binding for each
action and the live status (Ready / No binding / Needs ViGEmBus).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QCheckBox, QMessageBox, QDialog, QDialogButtonBox,
    QRadioButton, QButtonGroup, QFrame, QSizePolicy,
)

from edc.core.binds_reader import ActionBinding, load_bindings

log = logging.getLogger(__name__)

_STATUS_COLORS = {
    "ready":          "#6BCB77",
    "no_keyboard":    "#FF8C00",
    "no_controller":  "#FF8C00",
    "no_binding":     "#888888",
    "needs_vigem":    "#FF6B6B",
}

_COL_ENABLED = 0
_COL_PHRASE  = 1
_COL_ACTION  = 2
_COL_KEY     = 3
_COL_STATUS  = 4


class _AddEditDialog(QDialog):
    """Dialog for adding or editing a voice command entry."""

    def __init__(self, parent, bindings: dict[str, ActionBinding],
                 phrase: str = "", action: str = "", enabled: bool = True,
                 repeat: int = 1, confirm: str = "", input_pref: str = "controller"):
        super().__init__(parent)
        self.setWindowTitle("Voice Command")
        self.setMinimumWidth(420)
        self._bindings = bindings
        self._input_pref = input_pref

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Phrase (what you say after the trigger word):"))
        self._phrase_edit = QLineEdit(phrase)
        layout.addWidget(self._phrase_edit)

        layout.addWidget(QLabel("Elite Dangerous action:"))
        self._action_combo = QComboBox()
        self._action_combo.setEditable(True)
        self._action_combo.addItems(sorted(bindings.keys()))
        if action:
            idx = self._action_combo.findText(action)
            if idx >= 0:
                self._action_combo.setCurrentIndex(idx)
            else:
                self._action_combo.setCurrentText(action)
        self._action_combo.currentTextChanged.connect(self._refresh_status)
        layout.addWidget(self._action_combo)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._status_label)

        layout.addWidget(QLabel("Repeat (for pip commands — tap N times):"))
        self._repeat_combo = QComboBox()
        for i in range(1, 5):
            self._repeat_combo.addItem(str(i), i)
        self._repeat_combo.setCurrentIndex(repeat - 1)
        layout.addWidget(self._repeat_combo)

        layout.addWidget(QLabel("Confirm phrase (TTS spoken after command fires, blank = silent):"))
        self._confirm_edit = QLineEdit(confirm)
        self._confirm_edit.setPlaceholderText("e.g. Boosting.")
        layout.addWidget(self._confirm_edit)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(enabled)
        layout.addWidget(self._enabled_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_status()

    def _refresh_status(self):
        action = self._action_combo.currentText()
        ab = self._bindings.get(action)
        if not ab:
            self._status_label.setText("⚠ Action not found in your binds file")
            self._status_label.setStyleSheet("color: #888888; font-size: 11px;")
            return
        resolved = ab.resolve(self._input_pref)
        if resolved:
            key_str = resolved.key
            if resolved.modifiers:
                key_str = " + ".join(resolved.modifiers + [resolved.key])
            src = "controller" if resolved.is_controller else "keyboard"
            self._status_label.setText(f"✓ Ready — {src}: {key_str}")
            self._status_label.setStyleSheet("color: #6BCB77; font-size: 11px;")
        else:
            self._status_label.setText("⚠ No binding found — add one in ED Controls")
            self._status_label.setStyleSheet("color: #FF8C00; font-size: 11px;")

    def result_data(self) -> dict:
        return {
            "phrase":   self._phrase_edit.text().strip().lower(),
            "action":   self._action_combo.currentText().strip(),
            "enabled":  self._enabled_check.isChecked(),
            "repeat":   self._repeat_combo.currentData(),
            "confirm":  self._confirm_edit.text().strip(),
        }


class VoiceCommandsPanel(QWidget):
    """Main voice commands configuration panel."""

    commands_changed = pyqtSignal()

    def __init__(self, config_path: Path):
        super().__init__()
        self._config_path = config_path
        self._bindings: dict[str, ActionBinding] = {}
        self._data: dict = {"trigger_word": "ship", "input_preference": "controller", "commands": []}
        self._vigem_ok: Optional[bool] = None

        self._build_ui()
        self._load_config()
        self._load_bindings()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Input preference ──────────────────────────────────────────────
        pref_frame = QFrame()
        pref_frame.setStyleSheet("QFrame { background: #111; border-radius: 4px; padding: 4px; }")
        pref_layout = QHBoxLayout(pref_frame)
        pref_layout.addWidget(QLabel("Input preference:"))

        self._pref_group = QButtonGroup(self)
        self._radio_controller = QRadioButton("Controller")
        self._radio_keyboard = QRadioButton("Keyboard")
        self._pref_group.addButton(self._radio_controller)
        self._pref_group.addButton(self._radio_keyboard)
        pref_layout.addWidget(self._radio_controller)
        pref_layout.addWidget(self._radio_keyboard)
        pref_layout.addStretch()
        self._radio_controller.toggled.connect(self._on_pref_changed)
        root.addWidget(pref_frame)

        # ── ViGEmBus status ───────────────────────────────────────────────
        vigem_frame = QFrame()
        vigem_frame.setStyleSheet("QFrame { background: #111; border-radius: 4px; padding: 4px; }")
        vigem_layout = QHBoxLayout(vigem_frame)
        self._vigem_label = QLabel("Controller simulation: checking…")
        self._vigem_label.setStyleSheet("font-size: 11px;")
        vigem_layout.addWidget(self._vigem_label)
        self._vigem_btn = QPushButton("Install ViGEmBus")
        self._vigem_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._vigem_btn.setVisible(False)
        self._vigem_btn.clicked.connect(self._install_vigem)
        vigem_layout.addWidget(self._vigem_btn)
        root.addWidget(vigem_frame)

        # ── Trigger word ──────────────────────────────────────────────────
        trig_layout = QHBoxLayout()
        trig_layout.addWidget(QLabel("Trigger word:"))
        self._trigger_edit = QLineEdit()
        self._trigger_edit.setMaximumWidth(140)
        self._trigger_edit.setPlaceholderText("ship")
        self._trigger_edit.editingFinished.connect(self._save_config)
        trig_layout.addWidget(self._trigger_edit)
        trig_layout.addWidget(QLabel("(say this before every command)"))
        trig_layout.addStretch()
        root.addLayout(trig_layout)

        # ── Table ─────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["On", "Phrase", "Action", "Key", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        root.addWidget(self._table, 1)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_command)
        btn_edit = QPushButton("Edit")
        btn_edit.clicked.connect(self._edit_command)
        btn_delete = QPushButton("Delete")
        btn_delete.clicked.connect(self._delete_command)
        btn_reload = QPushButton("Reload Binds")
        btn_reload.clicked.connect(self._reload_bindings)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_reload)
        root.addLayout(btn_layout)

    # ── Config I/O ────────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            if self._config_path.exists():
                self._data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Failed to load voice_commands.json: %s", exc)

        pref = self._data.get("input_preference", "controller")
        self._radio_controller.setChecked(pref == "controller")
        self._radio_keyboard.setChecked(pref == "keyboard")
        self._trigger_edit.setText(self._data.get("trigger_word", "ship"))

    def _save_config(self):
        self._data["trigger_word"]      = self._trigger_edit.text().strip() or "ship"
        self._data["input_preference"]  = "controller" if self._radio_controller.isChecked() else "keyboard"
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.error("Failed to save voice_commands.json: %s", exc)
        self.commands_changed.emit()

    # ── Bindings ──────────────────────────────────────────────────────────────

    def _load_bindings(self):
        self._bindings = load_bindings()
        self._check_vigem()
        self._refresh_table()

    def _reload_bindings(self):
        self._bindings = load_bindings()
        self._check_vigem()
        self._refresh_table()

    # ── ViGEmBus ──────────────────────────────────────────────────────────────

    def _check_vigem(self):
        try:
            import vgamepad as vg
            vg.VX360Gamepad()
            self._vigem_ok = True
            self._vigem_label.setText("Controller simulation: ✓ ViGEmBus detected")
            self._vigem_label.setStyleSheet("color: #6BCB77; font-size: 11px;")
            self._vigem_btn.setVisible(False)
        except Exception:
            self._vigem_ok = False
            self._vigem_label.setText("Controller simulation: ⚠ ViGEmBus not installed")
            self._vigem_label.setStyleSheet("color: #FF8C00; font-size: 11px;")
            self._vigem_btn.setVisible(True)

    def _install_vigem(self):
        reply = QMessageBox.question(
            self, "Install ViGEmBus",
            "EDChronicle will download and run the ViGEmBus installer (~2 MB).\n"
            "Windows will ask for administrator permission.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from edc.core.ship_command_dispatcher import ShipCommandDispatcher
        disp = ShipCommandDispatcher()
        self._vigem_label.setText("Controller simulation: installing…")
        ok = disp.install_vigem()
        if ok:
            self._check_vigem()
        else:
            QMessageBox.warning(self, "Install Failed",
                                "ViGEmBus installation failed. Please install it manually from:\n"
                                "https://github.com/nefarius/ViGEmBus/releases")

    # ── Table ─────────────────────────────────────────────────────────────────

    def _input_pref(self) -> str:
        return "controller" if self._radio_controller.isChecked() else "keyboard"

    def _resolve_display(self, action: str) -> tuple[str, str]:
        """Return (key_display, status) for a given action."""
        ab = self._bindings.get(action)
        if not ab:
            return "—", "no_binding"

        pref = self._input_pref()
        resolved = ab.resolve(pref)
        if not resolved:
            return "—", f"no_{pref}"

        key_str = resolved.key
        if resolved.modifiers:
            key_str = " + ".join(resolved.modifiers + [resolved.key])
        src = "ctrl" if resolved.is_controller else "kb"

        # Determine status
        if resolved.is_controller and not self._vigem_ok:
            return f"{src}: {key_str}", "needs_vigem"
        return f"{src}: {key_str}", "ready"

    def _refresh_table(self):
        commands = self._data.get("commands", [])
        self._table.setRowCount(len(commands))

        for row, cmd in enumerate(commands):
            action  = cmd.get("action", "")
            phrase  = cmd.get("phrase", "")
            enabled = cmd.get("enabled", True)

            key_disp, status = self._resolve_display(action)

            # Enabled checkbox
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(row, _COL_ENABLED, chk)

            self._table.setItem(row, _COL_PHRASE,  QTableWidgetItem(phrase))
            self._table.setItem(row, _COL_ACTION,  QTableWidgetItem(action))
            self._table.setItem(row, _COL_KEY,     QTableWidgetItem(key_disp))

            status_item = QTableWidgetItem(_status_label(status))
            color = _STATUS_COLORS.get(status, "#888888")
            status_item.setForeground(Qt.GlobalColor.white)
            status_item.setData(Qt.ItemDataRole.ForegroundRole,
                                __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(color))
            self._table.setItem(row, _COL_STATUS, status_item)

        self._table.itemChanged.connect(self._on_check_changed)

    def _on_check_changed(self, item: QTableWidgetItem):
        if item.column() != _COL_ENABLED:
            return
        row = item.row()
        cmds = self._data.get("commands", [])
        if 0 <= row < len(cmds):
            cmds[row]["enabled"] = item.checkState() == Qt.CheckState.Checked
            self._save_config()

    def _on_pref_changed(self):
        self._save_config()
        self._table.itemChanged.disconnect()
        self._refresh_table()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_command(self):
        dlg = _AddEditDialog(self, self._bindings, input_pref=self._input_pref())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data["phrase"] or not data["action"]:
            return
        self._data.setdefault("commands", []).append(data)
        self._save_config()
        self._table.itemChanged.disconnect()
        self._refresh_table()

    def _edit_command(self):
        row = self._table.currentRow()
        cmds = self._data.get("commands", [])
        if row < 0 or row >= len(cmds):
            return
        cmd = cmds[row]
        dlg = _AddEditDialog(
            self, self._bindings,
            phrase=cmd.get("phrase", ""),
            action=cmd.get("action", ""),
            enabled=cmd.get("enabled", True),
            repeat=cmd.get("repeat", 1),
            confirm=cmd.get("confirm", ""),
            input_pref=self._input_pref(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cmds[row] = dlg.result_data()
        self._save_config()
        self._table.itemChanged.disconnect()
        self._refresh_table()

    def _delete_command(self):
        row = self._table.currentRow()
        cmds = self._data.get("commands", [])
        if row < 0 or row >= len(cmds):
            return
        phrase = cmds[row].get("phrase", "?")
        reply = QMessageBox.question(
            self, "Delete command",
            f"Remove \"{phrase}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cmds.pop(row)
        self._save_config()
        self._table.itemChanged.disconnect()
        self._refresh_table()

    # ── Public API (read by VoiceCommandListener) ─────────────────────────────

    def active_commands(self) -> list[dict]:
        """Return only enabled commands with their resolved binding."""
        pref = self._input_pref()
        result = []
        for cmd in self._data.get("commands", []):
            if not cmd.get("enabled", True):
                continue
            ab = self._bindings.get(cmd.get("action", ""))
            if not ab:
                continue
            binding = ab.resolve(pref)
            if not binding:
                continue
            result.append({**cmd, "_binding": binding})
        return result

    def trigger_word(self) -> str:
        return self._data.get("trigger_word", "ship")

    def all_phrases(self) -> list[str]:
        """All enabled phrase words for Vosk grammar construction."""
        words = set()
        for cmd in self._data.get("commands", []):
            if cmd.get("enabled", True):
                for w in cmd.get("phrase", "").lower().split():
                    words.add(w)
        return sorted(words)


def _status_label(status: str) -> str:
    return {
        "ready":         "Ready",
        "no_keyboard":   "No keyboard binding",
        "no_controller": "No controller binding",
        "no_binding":    "Not in binds file",
        "needs_vigem":   "Needs ViGEmBus",
    }.get(status, status)
