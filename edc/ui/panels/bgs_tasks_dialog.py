# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""BGS Tasks -- the squadron's current BGS objectives, entered by hand,
each with live progress from data the app already records. See
docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
from __future__ import annotations

import html
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, PP_MODES, STATUS_COLORS, STATUS_DONE, TASK_LABELS, TASK_TYPES, TYPE_COLORS, build_task_views,
    describe_detection, detect_powerplay_mode, task_title, validate_task_input,
)
from edc.ui import formatting as fmt
from edc.ui.style import CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE

log = logging.getLogger("edc.bgs_tasks")

_LINE_STYLE = "background:transparent; border:none; color:#c8c8c8;"
_LINE_STATE_STYLES = {
    "met": "background:transparent; border:none; color:#6BCB77;",
    "over": "background:transparent; border:none; color:#FFB347;",
}
_DIM_STYLE ="background:transparent; border:none; color:#888888; font-size:11px;"
_GUIDE_STYLE = "background:transparent; border:none; color:#a8a8a8;"
_WARN_STYLE ="background:transparent; border:none; color:#FFB347;"
_SMALL_BTN = (
    "QPushButton { background:#101c2a; color:#c8c8c8; border:1px solid #2a3a4a;"
    " border-radius:3px; padding:1px 8px; }"
    "QPushButton:hover { background:#1a2a3a; }"
)


class BgsTasksDialog(QDialog):
    """Non-modal window listing every squadron BGS task with its progress."""

    def __init__(self, panel):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self.setWindowTitle("BGS Tasks")
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel("SQUADRON BGS TASKS")
        hdr.setStyleSheet(_HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        form = QHBoxLayout()
        self._system_edit = QLineEdit()
        self._system_edit.setPlaceholderText("System")
        self._type_combo = QComboBox()
        for t in TASK_TYPES:
            self._type_combo.addItem(TASK_LABELS[t], t)
        self._faction_edit = QLineEdit()
        self._faction_edit.setPlaceholderText("Faction to support")
        self._opponent_edit = QLineEdit()
        self._opponent_edit.setPlaceholderText("Opposing faction")
        # PowerPlay job as the squadron's objective states it; Auto-detect
        # uses your journal, else EDSM's daily dump.
        self._pp_mode_combo = QComboBox()
        self._pp_mode_combo.addItem("Auto-detect", "")
        for m in PP_MODES:
            self._pp_mode_combo.addItem(m, m)
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("Note (optional)")
        add_btn = QPushButton("Add task")
        add_btn.clicked.connect(self._on_add)
        for w in (self._system_edit, self._type_combo, self._pp_mode_combo, self._faction_edit,
                  self._opponent_edit, self._note_edit):
            form.addWidget(w)
        form.addWidget(add_btn)
        layout.addLayout(form)

        self._pp_detect_label = QLabel("")
        self._pp_detect_label.setWordWrap(True)
        self._pp_detect_label.setStyleSheet(_DIM_STYLE)
        layout.addWidget(self._pp_detect_label)

        self._form_error = QLabel("")
        self._form_error.setStyleSheet("background:transparent; border:none; color:#FF6B6B;")
        layout.addWidget(self._form_error)

        self._tick_label = QLabel("")
        self._tick_label.setStyleSheet(_DIM_STYLE)
        layout.addWidget(self._tick_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll, 1)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setSpacing(8)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        self._empty_label = QLabel("No tasks yet — add the squadron's objectives above.")
        self._empty_label.setStyleSheet("background:transparent; border:none; color:#666666;")
        self._content_layout.addWidget(self._empty_label)

        footer = QLabel(
            "Boost targets are community guidance (SINC BGS Guide 2024, sized by system population; "
            "Settings values when population is unknown), not Frontier numbers."
        )
        footer.setWordWrap(True)
        footer.setStyleSheet(_DIM_STYLE)
        layout.addWidget(footer)

        self._cards: list = []
        self._completers_loaded = False
        self._type_combo.currentIndexChanged.connect(self._update_form_fields)
        self._system_edit.editingFinished.connect(self._update_faction_completers)
        self._system_edit.editingFinished.connect(self._update_pp_detection)
        self._update_form_fields()

    # ── form ──────────────────────────────────────────────────────────────

    def _update_form_fields(self) -> None:
        t = self._type_combo.currentData()
        self._faction_edit.setEnabled(t in ("boost", "hinder", "vote", "fight"))
        self._faction_edit.setPlaceholderText("Faction to hinder" if t == "hinder" else "Faction to support")
        self._opponent_edit.setEnabled(t in ("vote", "fight"))
        self._pp_mode_combo.setVisible(t == "powerplay")
        self._update_pp_detection()

    def _update_pp_detection(self) -> None:
        """Preview of the PowerPlay job for the typed system, before adding."""
        system = self._system_edit.text().strip()
        if self._type_combo.currentData() != "powerplay" or not system:
            self._pp_detect_label.setText("")
            return
        pledged_getter = getattr(self._panel, "pledged_power_getter", None)
        pledged = pledged_getter() if pledged_getter else ""
        if not pledged:
            self._pp_detect_label.setText("Pledge to a power to detect the PowerPlay job here.")
            return
        try:
            resolved = self._panel._repo.resolve_system(system)
            pp = self._panel._repo.get_system_powerplay_snapshot(resolved[0]) if resolved else None
        except Exception:
            log.exception("Failed to read PowerPlay snapshot for task preview")
            pp = None
        edsm = getattr(self._panel, "edsm_powerplay", None)
        edsm_row = edsm.get_controller_by_name(resolved[1] if resolved else system) if (edsm and not pp) else None
        allies_getter = getattr(self._panel, "allies_getter", None)
        det = detect_powerplay_mode(pledged, pp, edsm_row, allies_getter() if allies_getter else frozenset())
        self._pp_detect_label.setText(describe_detection(det))

    def _make_completer(self, names: list) -> QCompleter:
        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        return completer

    def _load_system_completer(self) -> None:
        try:
            names = self._panel._repo.get_all_system_names()
        except Exception:
            log.exception("Failed to load system names for BGS task entry")
            return
        self._system_edit.setCompleter(self._make_completer(names))
        self._completers_loaded = True

    def _update_faction_completers(self) -> None:
        try:
            resolved = self._panel._repo.resolve_system(self._system_edit.text())
            names = self._panel._repo.get_known_faction_names(resolved[0]) if resolved else []
        except Exception:
            log.exception("Failed to load faction names for BGS task entry")
            return
        self._faction_edit.setCompleter(self._make_completer(names))
        self._opponent_edit.setCompleter(self._make_completer(names))

    def _on_add(self) -> None:
        system = self._system_edit.text().strip()
        task_type = self._type_combo.currentData()
        faction = self._faction_edit.text().strip() if self._faction_edit.isEnabled() else ""
        opponent = self._opponent_edit.text().strip() if self._opponent_edit.isEnabled() else ""
        note = self._note_edit.text().strip()
        error = validate_task_input(system, task_type, faction, opponent, note)
        self._form_error.setText(error)
        if error:
            return
        try:
            pp_mode = self._pp_mode_combo.currentData() if task_type == "powerplay" else None
            self._panel._repo.add_bgs_task(system, task_type, faction or None, opponent or None, note or None,
                                           pp_mode=pp_mode or None)
        except Exception:
            log.exception("Failed to add BGS task")
            self._form_error.setText("Couldn't save the task — see the log.")
            return
        for edit in (self._system_edit, self._faction_edit, self._opponent_edit, self._note_edit):
            edit.clear()
        self._pp_mode_combo.setCurrentIndex(0)
        self._pp_detect_label.setText("")
        self.refresh()
        self._changed()

    # ── task actions ─────────────────────────────────────────────────────

    def _changed(self) -> None:
        signal = getattr(self._panel, "bgs_tasks_changed", None)
        if signal is not None:
            signal.emit()

    def _move(self, task_id: int, direction: int) -> None:
        try:
            self._panel._repo.move_bgs_task(task_id, direction)
        except Exception:
            log.exception("Failed to move BGS task")
        self.refresh()
        self._changed()

    def _remove(self, task_id: int) -> None:
        try:
            self._panel._repo.delete_bgs_task(task_id)
        except Exception:
            log.exception("Failed to remove BGS task")
        self.refresh()
        self._changed()

    # ── rendering ────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._completers_loaded:
            self._load_system_completer()
        self.refresh()

    def refresh(self) -> None:
        tick_iso = getattr(self._panel, "_latest_known_tick", None)
        if tick_iso:
            age_txt, _ = fmt.relative_time(tick_iso)
            self._tick_label.setText(f"Your progress since last tick: {age_txt}")
            since = tick_iso
        else:
            self._tick_label.setText("No BGS tick detected yet — progress counts all recorded activity.")
            since = "1970-01-01T00:00:00Z"
        getter = getattr(self._panel, "bgs_limits_getter", None)
        limits = getter() if getter else dict(DEFAULT_LIMITS)
        pledged_getter = getattr(self._panel, "pledged_power_getter", None)
        try:
            views = build_task_views(
                self._panel._repo, since, limits,
                pledged=pledged_getter() if pledged_getter else "",
                pp_activities=getattr(self._panel, "pp_activities", None),
                edsm_powerplay=getattr(self._panel, "edsm_powerplay", None),
            )
        except Exception:
            log.exception("Failed to build BGS task views")
            views = []
        self._render(views)

    def _render(self, views: list) -> None:
        for card in self._cards:
            self._content_layout.removeWidget(card)
            card.deleteLater()
        self._cards = []
        self._empty_label.setVisible(not views)
        for view in views:
            card = self._make_card(view)
            self._content_layout.addWidget(card)
            self._cards.append(card)

    def _make_card(self, view: dict) -> QFrame:
        task = view["task"]
        card = QFrame()
        accent = TYPE_COLORS.get(task["task_type"], "#c8c8c8")
        done_tint = " QFrame { background:#0f2418; }" if view["status"] == STATUS_DONE else ""
        card.setStyleSheet(_CARD_STYLE + f" QFrame {{ border-left:4px solid {accent}; }}" + done_tint)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(8, 6, 8, 8)
        card_l.setSpacing(3)

        top = QHBoxLayout()
        title = QLabel(task_title(task))
        title.setStyleSheet(_HDR_STYLE + f" color:{accent};")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        if view["status"]:
            status = QLabel(view["status"])
            color = STATUS_COLORS.get(view["status"], "#c8c8c8")
            status.setStyleSheet(f"background:transparent; border:none; color:{color}; font-weight:700;")
            top.addWidget(status)
        task_id = task["id"]
        for text, handler in (
            ("↑", lambda _checked=False, i=task_id: self._move(i, -1)),
            ("↓", lambda _checked=False, i=task_id: self._move(i, +1)),
            ("Remove", lambda _checked=False, i=task_id: self._remove(i)),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(_SMALL_BTN)
            btn.clicked.connect(handler)
            top.addWidget(btn)
        card_l.addLayout(top)

        if view.get("guide"):
            lbl = QLabel(
                f'<span style="color:{accent}; font-weight:700;">What to do:</span> {html.escape(view["guide"])}'
            )
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_GUIDE_STYLE)
            card_l.addWidget(lbl)
        for line, state in zip(view["lines"], view.get("line_states") or [""] * len(view["lines"])):
            lbl = QLabel(line)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_LINE_STATE_STYLES.get(state, _LINE_STYLE))
            card_l.addWidget(lbl)
        for warning in view["warnings"]:
            lbl = QLabel(f"⚠ {warning}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_WARN_STYLE)
            card_l.addWidget(lbl)
        if task["system_address"] is None and task["task_type"] != "note":
            lbl = QLabel("System not seen yet — progress appears once you visit it or EDDN reports it.")
            lbl.setStyleSheet(_DIM_STYLE)
            card_l.addWidget(lbl)
        if view.get("updated_at"):
            age_txt, _ = fmt.relative_time(view["updated_at"])
            lbl = QLabel(f"Updated {age_txt}")
            lbl.setStyleSheet(_DIM_STYLE)
            card_l.addWidget(lbl)
        return card
