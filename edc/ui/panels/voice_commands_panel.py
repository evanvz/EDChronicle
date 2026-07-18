"""
Voice Commands settings panel.

Lets the user configure ship voice commands: add, edit, enable/disable,
and delete entries. Shows the resolved keyboard binding for each action and
the live status (Ready / No binding / Gamepad-only).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QCheckBox, QMessageBox, QDialog, QDialogButtonBox,
    QFrame, QSizePolicy,
    QListWidget, QListWidgetItem, QSlider,
)

from edc.core.binds_reader import ActionBinding, load_bindings

log = logging.getLogger(__name__)

_STATUS_COLORS = {
    "ready":           "#6BCB77",
    "no_keyboard":     "#FFD700",
    "no_controller":   "#FF8C00",
    "no_binding":      "#888888",
    "controller_only": "#FFD700",
    "bad_vocab":       "#FF6B6B",
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
                 repeat: int = 1, confirm: str = "",
                 existing_commands: list | None = None,
                 models_dir: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Voice Command")
        self.setMinimumWidth(460)
        self._bindings = bindings
        self._input_pref = "keyboard"
        self._selected_action = action
        self._models_dir = models_dir
        # Map action → existing command entry for pre-fill on Add
        self._existing: dict[str, dict] = (
            {c.get("action", ""): c for c in existing_commands} if existing_commands else {}
        )

        # Build sorted list of (action_key, display_label) once.
        # Label is the in-game menu name only; search still matches the raw
        # action code too since _populate_list checks both key and label.
        self._action_items: list[tuple[str, str]] = sorted(
            ((k, ab.display_name) for k, ab in bindings.items()),
            key=lambda x: x[1].lower(),
        )

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Phrase (what you say after the trigger word):"))
        self._phrase_edit = QLineEdit(phrase)
        layout.addWidget(self._phrase_edit)

        self._vocab_warning = QLabel("")
        self._vocab_warning.setStyleSheet("color: #FF6B6B; font-size: 11px;")
        self._vocab_warning.setWordWrap(True)
        layout.addWidget(self._vocab_warning)

        layout.addWidget(QLabel("Elite Dangerous action:"))
        self._action_search = QLineEdit()
        self._action_search.setPlaceholderText("Search by name or keyword (e.g. 'boost', 'landing', 'power')…")
        layout.addWidget(self._action_search)

        self._action_list = QListWidget()
        self._action_list.setMaximumHeight(160)
        self._action_list.setStyleSheet("""
            QListWidget {
                background: #101010;
                border: 1px solid #2A2A2A;
                color: #E6E6E6;
            }
            QListWidget::item { padding: 3px 6px; color: #E6E6E6; }
            QListWidget::item:hover { background: #1F1F1F; color: #ffffff; }
            QListWidget::item:selected { background: #FF8C00; color: #000000; }
            QListWidget::item:selected:hover { background: #FFA733; color: #000000; }
        """)
        layout.addWidget(self._action_list)

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

        self._action_search.textChanged.connect(self._on_search_changed)
        self._action_list.currentItemChanged.connect(self._on_list_selection)
        self._phrase_edit.textChanged.connect(self._check_vocab)

        self._populate_list("")
        if action:
            self._select_action(action)
        self._refresh_status()
        self._check_vocab()

    def _check_vocab(self):
        if not self._models_dir:
            return
        from edc.audio.voice_commands import missing_vocab_words
        words = self._phrase_edit.text().strip().lower().split()
        missing = missing_vocab_words(words, self._models_dir)
        if missing:
            plural = "word isn't" if len(missing) == 1 else "words aren't"
            self._vocab_warning.setText(
                f"⚠ The {plural} recognised by the speech model: {', '.join(missing)} — "
                "this phrase can never be detected. Try a different word."
            )
        else:
            self._vocab_warning.setText("")

    def _populate_list(self, query: str):
        self._action_list.clear()
        q = query.lower()
        for key, label in self._action_items:
            if not q or q in key.lower() or q in label.lower():
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self._action_list.addItem(item)

    def _select_action(self, action: str):
        for i in range(self._action_list.count()):
            item = self._action_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == action:
                self._action_list.setCurrentItem(item)
                self._action_list.scrollToItem(item)
                return

    def _on_search_changed(self, text: str):
        self._populate_list(text)
        # Restore selection if it's still visible after filter
        if self._selected_action:
            self._select_action(self._selected_action)
        self._refresh_status()

    def _on_list_selection(self, item: QListWidgetItem):
        if not item:
            return
        self._selected_action = item.data(Qt.ItemDataRole.UserRole)
        existing = self._existing.get(self._selected_action)
        if existing:
            self._phrase_edit.setText(existing.get("phrase", ""))
            self._confirm_edit.setText(existing.get("confirm", ""))
            self._repeat_combo.setCurrentIndex(max(0, existing.get("repeat", 1) - 1))
            self._enabled_check.setChecked(existing.get("enabled", True))
        self._refresh_status()

    def _refresh_status(self):
        ab = self._bindings.get(self._selected_action or "")
        if not ab:
            self._status_label.setText("⚠ Select an action from the list above")
            self._status_label.setStyleSheet("color: #888888; font-size: 11px;")
            return
        resolved = ab.resolve(self._input_pref)
        if resolved:
            key_str = resolved.key
            if resolved.modifiers:
                key_str = " + ".join(resolved.modifiers + [resolved.key])
            src = "controller" if resolved.is_controller else "keyboard"
            if resolved.is_controller and ab.keyboard is None:
                self._status_label.setText(
                    f"⚠ Gamepad-only ({key_str}) — may not respond if you use Steam Input "
                    "or another controller layer. Add a keyboard bind in ED for reliability."
                )
                self._status_label.setStyleSheet("color: #FFD700; font-size: 11px;")
            else:
                self._status_label.setText(f"✓ Ready — {src}: {key_str}")
                self._status_label.setStyleSheet("color: #6BCB77; font-size: 11px;")
        else:
            self._status_label.setText("⚠ No binding found — add one in ED Controls")
            self._status_label.setStyleSheet("color: #FF8C00; font-size: 11px;")

    def result_data(self) -> dict:
        return {
            "phrase":   self._phrase_edit.text().strip().lower(),
            "action":   self._selected_action or "",
            "enabled":  self._enabled_check.isChecked(),
            "repeat":   self._repeat_combo.currentData(),
            "confirm":  self._confirm_edit.text().strip(),
        }


class VoiceCommandsPanel(QWidget):
    """Main voice commands configuration panel."""

    commands_changed = pyqtSignal()
    feedback_test_requested = pyqtSignal()

    def __init__(self, config_path: Path, models_dir: Path | None = None):
        super().__init__()
        self._config_path = config_path
        self._models_dir = models_dir
        self._bindings: dict[str, ActionBinding] = {}
        self._data: dict = {"trigger_word": "ship", "input_preference": "keyboard", "commands": []}

        self._build_ui()
        self._load_config()
        self._load_bindings()
        self._populate_mic_combo()
        self._populate_output_combo()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Trigger word ──────────────────────────────────────────────────
        trig_layout = QHBoxLayout()
        trig_layout.addWidget(QLabel("Ship trigger word:"))
        self._trigger_edit = QLineEdit()
        self._trigger_edit.setMaximumWidth(140)
        self._trigger_edit.setPlaceholderText("ship")
        self._trigger_edit.editingFinished.connect(self._save_config)
        trig_layout.addWidget(self._trigger_edit)
        trig_layout.addWidget(QLabel("(say this before every ship command)"))
        trig_layout.addStretch()
        root.addLayout(trig_layout)

        # ── Nav trigger word ─────────────────────────────────────────────────
        nav_trig_layout = QHBoxLayout()
        nav_trig_layout.addWidget(QLabel("Menu trigger word:"))
        self._nav_trigger_edit = QLineEdit()
        self._nav_trigger_edit.setMaximumWidth(140)
        self._nav_trigger_edit.setPlaceholderText("hud")
        self._nav_trigger_edit.editingFinished.connect(self._save_config)
        nav_trig_layout.addWidget(self._nav_trigger_edit)
        nav_trig_layout.addWidget(QLabel("(say this before every tab name, e.g. \"hud overview\")"))
        nav_trig_layout.addStretch()
        root.addLayout(nav_trig_layout)

        # ── Microphone selection ────────────────────────────────────────────
        mic_layout = QHBoxLayout()
        mic_layout.addWidget(QLabel("Microphone:"))
        self._mic_combo = QComboBox()
        self._mic_combo.setMinimumWidth(260)
        mic_layout.addWidget(self._mic_combo)
        btn_refresh_mics = QPushButton("Refresh")
        btn_refresh_mics.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_refresh_mics.clicked.connect(self._populate_mic_combo)
        mic_layout.addWidget(btn_refresh_mics)
        mic_layout.addStretch()
        root.addLayout(mic_layout)
        self._mic_warning = QLabel("")
        self._mic_warning.setStyleSheet("color: #FF8C00; font-size: 11px;")
        root.addWidget(self._mic_warning)

        # ── Audio output selection ──────────────────────────────────────────
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("Audio output:"))
        self._output_combo = QComboBox()
        self._output_combo.setMinimumWidth(260)
        out_layout.addWidget(self._output_combo)
        btn_refresh_output = QPushButton("Refresh")
        btn_refresh_output.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_refresh_output.clicked.connect(self._populate_output_combo)
        out_layout.addWidget(btn_refresh_output)
        out_layout.addStretch()
        root.addLayout(out_layout)

        # ── Feedback volume ─────────────────────────────────────────────────
        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("Feedback volume:"))
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(50)
        self._volume_slider.setMaximumWidth(220)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        self._volume_slider.sliderReleased.connect(self._save_config)
        vol_layout.addWidget(self._volume_slider)
        self._volume_label = QLabel("50%")
        self._volume_label.setMinimumWidth(40)
        vol_layout.addWidget(self._volume_label)
        btn_test_volume = QPushButton("Test")
        btn_test_volume.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_test_volume.clicked.connect(self._on_test_volume)
        vol_layout.addWidget(btn_test_volume)
        vol_layout.addWidget(QLabel("(beeps, startup and confirm phrases — other voices unaffected)"))
        vol_layout.addStretch()
        root.addLayout(vol_layout)

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

        self._trigger_edit.setText(self._data.get("trigger_word", "ship"))
        self._nav_trigger_edit.setText(self._data.get("nav_trigger_word", "hud"))
        vol_pct = int(float(self._data.get("feedback_volume", 0.5)) * 100)
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(max(0, min(100, vol_pct)))
        self._volume_slider.blockSignals(False)
        self._volume_label.setText(f"{self._volume_slider.value()}%")

    def _save_config(self):
        self._data["trigger_word"]      = self._trigger_edit.text().strip() or "ship"
        self._data["nav_trigger_word"]  = self._nav_trigger_edit.text().strip() or "hud"
        self._data["input_preference"]  = "keyboard"
        self._data["input_device"]      = self._mic_combo.currentData() if self._mic_combo.count() else None
        self._data["output_device"]     = self._output_combo.currentData() if self._output_combo.count() else None
        self._data["feedback_volume"]   = self._volume_slider.value() / 100.0
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.error("Failed to save voice_commands.json: %s", exc)
        self.commands_changed.emit()

    def _on_volume_changed(self, value: int):
        self._volume_label.setText(f"{value}%")

    def _on_test_volume(self):
        self._save_config()
        self.feedback_test_requested.emit()

    def feedback_volume(self) -> float:
        """Voice-command feedback volume (0.0-1.0) — beeps, startup and
        confirm phrases. Independent of the main TTS/comms volumes."""
        return self._volume_slider.value() / 100.0

    # ── Microphone selection ─────────────────────────────────────────────────

    _LOOPBACK_HINTS = ("stereo mix", "what u hear", "loopback", "wave out")

    def _populate_mic_combo(self):
        self._mic_combo.blockSignals(True)
        self._mic_combo.clear()
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioInputs()
            names = [d.description() for d in devices]
        except Exception as exc:
            log.warning("Failed to enumerate microphones: %s", exc)
            names = []

        saved = self._data.get("input_device")
        for name in names:
            label = name
            if any(h in name.lower() for h in self._LOOPBACK_HINTS):
                label = f"{name}  (⚠ system audio — not a mic)"
            self._mic_combo.addItem(label, name)

        if saved:
            idx = self._mic_combo.findData(saved)
            if idx >= 0:
                self._mic_combo.setCurrentIndex(idx)
        self._mic_combo.blockSignals(False)
        try:
            self._mic_combo.currentIndexChanged.disconnect(self._on_mic_changed)
        except Exception:
            pass
        self._mic_combo.currentIndexChanged.connect(self._on_mic_changed)
        self._update_mic_warning()

    def _on_mic_changed(self):
        self._update_mic_warning()
        self._save_config()

    def _update_mic_warning(self):
        name = self._mic_combo.currentData() or ""
        if any(h in name.lower() for h in self._LOOPBACK_HINTS):
            self._mic_warning.setText(
                "⚠ This device captures system audio playback, not your voice — "
                "choose your headset/microphone instead."
            )
        else:
            self._mic_warning.setText("")

    def input_device(self) -> str | None:
        return self._data.get("input_device")

    # ── Audio output selection ───────────────────────────────────────────────

    def _populate_output_combo(self):
        self._output_combo.blockSignals(True)
        self._output_combo.clear()
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioOutputs()
            names = [d.description() for d in devices]
        except Exception as exc:
            log.warning("Failed to enumerate audio outputs: %s", exc)
            names = []

        saved = self._data.get("output_device")
        for name in names:
            self._output_combo.addItem(name, name)

        if saved:
            idx = self._output_combo.findData(saved)
            if idx >= 0:
                self._output_combo.setCurrentIndex(idx)
        self._output_combo.blockSignals(False)
        try:
            self._output_combo.currentIndexChanged.disconnect(self._on_output_changed)
        except Exception:
            pass
        self._output_combo.currentIndexChanged.connect(self._on_output_changed)

    def _on_output_changed(self):
        self._save_config()

    def output_device(self) -> str | None:
        return self._data.get("output_device")

    # ── Bindings ──────────────────────────────────────────────────────────────

    def _load_bindings(self):
        self._bindings = load_bindings()
        self._refresh_table()

    def _reload_bindings(self):
        self._bindings = load_bindings()
        self._refresh_table()

    # ── Table ─────────────────────────────────────────────────────────────────

    def _input_pref(self) -> str:
        return "keyboard"

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
        if resolved.is_controller:
            # No keyboard binding exists for this action — controller dispatch
            # isn't supported, so this command cannot be voice-fired until a
            # keyboard binding is added in ED's own Controls settings.
            return f"{src}: {key_str}", "controller_only"
        return f"{src}: {key_str}", "ready"

    def _refresh_table(self):
        def _display_name(cmd: dict) -> str:
            action = cmd.get("action", "")
            ab = self._bindings.get(action)
            return (ab.display_name if ab else action).lower()

        commands = self._data.get("commands", [])
        commands.sort(key=_display_name)
        self._table.setRowCount(len(commands))

        for row, cmd in enumerate(commands):
            action  = cmd.get("action", "")
            phrase  = cmd.get("phrase", "")
            enabled = cmd.get("enabled", True)

            key_disp, status = self._resolve_display(action)

            # A phrase with an unrecognised word can never be detected at all —
            # that takes priority over binding status, which is moot otherwise.
            if self._models_dir:
                from edc.audio.voice_commands import missing_vocab_words
                missing = missing_vocab_words(phrase.split(), self._models_dir)
                if missing:
                    status = "bad_vocab"

            # Enabled checkbox
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(row, _COL_ENABLED, chk)

            ab = self._bindings.get(action)
            action_disp = ab.display_name if ab else action
            self._table.setItem(row, _COL_PHRASE,  QTableWidgetItem(phrase))
            self._table.setItem(row, _COL_ACTION,  QTableWidgetItem(action_disp))
            self._table.setItem(row, _COL_KEY,     QTableWidgetItem(key_disp))

            color = _STATUS_COLORS.get(status, "#888888")
            status_label = QLabel(f'<span style="color:{color};">{_status_label(status)}</span>')
            status_label.setTextFormat(Qt.TextFormat.RichText)
            status_label.setStyleSheet("background: transparent; padding: 2px 6px;")
            self._table.setCellWidget(row, _COL_STATUS, status_label)

        self._table.itemChanged.connect(self._on_check_changed)

    def _on_check_changed(self, item: QTableWidgetItem):
        if item.column() != _COL_ENABLED:
            return
        row = item.row()
        cmds = self._data.get("commands", [])
        if 0 <= row < len(cmds):
            cmds[row]["enabled"] = item.checkState() == Qt.CheckState.Checked
            self._save_config()


    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _find_duplicate(self, action: str, phrase: str, exclude_row: int = -1) -> str | None:
        """Return a warning message if the action or phrase is already used elsewhere."""
        for i, cmd in enumerate(self._data.get("commands", [])):
            if i == exclude_row:
                continue
            if cmd.get("action") == action:
                return (f"Action \"{action}\" is already assigned to the phrase "
                        f"\"{cmd.get('phrase', '')}\".")
            if cmd.get("phrase", "").lower() == phrase.lower():
                return (f"Phrase \"{phrase}\" is already used for action "
                        f"\"{cmd.get('action', '')}\".")
        return None

    def _add_command(self):
        dlg = _AddEditDialog(self, self._bindings,
                             existing_commands=self._data.get("commands", []),
                             models_dir=self._models_dir)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data["phrase"] or not data["action"]:
            return
        dup = self._find_duplicate(data["action"], data["phrase"])
        if dup:
            QMessageBox.warning(self, "Duplicate command", dup)
            return
        self._data.setdefault("commands", []).append(data)
        self._save_config()
        try:
            self._table.itemChanged.disconnect()
        except Exception:
            pass
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
            models_dir=self._models_dir,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data["phrase"] or not data["action"]:
            return
        dup = self._find_duplicate(data["action"], data["phrase"], exclude_row=row)
        if dup:
            QMessageBox.warning(self, "Duplicate command", dup)
            return
        cmds[row] = data
        self._save_config()
        try:
            self._table.itemChanged.disconnect()
        except Exception:
            pass
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
        try:
            self._table.itemChanged.disconnect()
        except Exception:
            pass
        self._refresh_table()

    # ── Public API (read by VoiceCommandListener) ─────────────────────────────

    def active_commands(self) -> list[dict]:
        """
        Return only enabled commands that resolve to a keyboard binding.
        Gamepad-only actions are excluded entirely — dispatch can't send
        controller input, so including them would put their phrase in the
        recognition grammar and speak a confirm without performing anything.
        """
        pref = self._input_pref()
        result = []
        for cmd in self._data.get("commands", []):
            if not cmd.get("enabled", True):
                continue
            ab = self._bindings.get(cmd.get("action", ""))
            if not ab:
                continue
            binding = ab.resolve(pref)
            if not binding or binding.is_controller:
                continue
            result.append({**cmd, "_binding": binding})
        return result

    def trigger_word(self) -> str:
        return self._data.get("trigger_word", "ship")

    def nav_trigger_word(self) -> str:
        return self._data.get("nav_trigger_word", "hud")


def _status_label(status: str) -> str:
    return {
        "ready":           "Ready",
        "no_keyboard":     "No keyboard binding",
        "no_controller":   "No controller binding",
        "no_binding":      "Not in binds file",
        "controller_only": "Gamepad-only — add keyboard bind in ED",
        "bad_vocab":       "Word not recognised by speech model",
    }.get(status, status)
