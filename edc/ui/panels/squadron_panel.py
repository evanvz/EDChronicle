"""Squadron tab — name, rank, rank history, and trophies from journal-
exposed squadron events. The game does not expose a member roster, chat,
or wing-mission data to third-party tools, so that's not something this
panel can show; the squadron-aligned minor faction BGS data is tracked
separately on the Player Faction tab.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame,
)

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"


class SquadronPanel(QWidget):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Status card ──────────────────────────────────────────────────
        status_card = QFrame()
        status_card.setStyleSheet(_CARD_STYLE)
        status_l = QVBoxLayout(status_card)
        status_l.setContentsMargins(8, 6, 8, 6)
        status_l.setSpacing(4)

        hdr = QLabel("SQUADRON")
        hdr.setStyleSheet(_HDR_STYLE)
        status_l.addWidget(hdr)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("background:transparent; border:none; color:#c8c8c8; font-size:13px;")
        status_l.addWidget(self._status_label)

        root.addWidget(status_card)

        # ── BGS pointer ──────────────────────────────────────────────────
        bgs_card = QFrame()
        bgs_card.setStyleSheet(_CARD_STYLE)
        bgs_l = QVBoxLayout(bgs_card)
        bgs_l.setContentsMargins(8, 6, 8, 6)
        bgs_l.setSpacing(4)

        bgs_hdr = QLabel("SQUADRON-ALIGNED FACTION (BGS)")
        bgs_hdr.setStyleSheet(_HDR_STYLE)
        bgs_l.addWidget(bgs_hdr)

        self._bgs_label = QLabel("")
        self._bgs_label.setWordWrap(True)
        self._bgs_label.setStyleSheet("background:transparent; border:none; color:#888888;")
        bgs_l.addWidget(self._bgs_label)

        root.addWidget(bgs_card)

        # ── Rank history ─────────────────────────────────────────────────
        history_hdr = QLabel("RANK HISTORY")
        history_hdr.setStyleSheet(_HDR_STYLE)
        root.addWidget(history_hdr)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(3)
        self._history_table.setHorizontalHeaderLabels(["Date", "Change", "Rank"])
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
        )
        h = self._history_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._history_table, 1)

    def refresh(self, state) -> None:
        name = getattr(state, "squadron_name", None)
        if not name:
            self._status_label.setText(
                "No squadron detected yet — this populates automatically once you're in one."
            )
            self._bgs_label.setText("")
            self._history_table.setRowCount(0)
            return

        rank = getattr(state, "squadron_rank", None)
        trophies = getattr(state, "squadron_trophies", 0) or 0
        status = getattr(state, "squadron_status", None)
        status_ts = getattr(state, "squadron_status_timestamp", None)

        rank_txt = f"Rank {rank}" if rank is not None else "Rank unknown"
        trophy_word = "trophy" if trophies == 1 else "trophies"
        lines = [f"<b>{name}</b> — {rank_txt} — {trophies} {trophy_word} won"]
        if status:
            lines.append(f"Last status: {status} ({status_ts or 'unknown date'})")
        self._status_label.setText("<br>".join(lines))

        try:
            overview = self._repo.get_player_faction_overview()
        except Exception:
            log.exception("Failed to load player faction overview")
            overview = None
        if overview:
            self._bgs_label.setText(
                f"{overview['faction_name']} — see the Player Faction tab for full system-by-system detail."
            )
        else:
            self._bgs_label.setText("No squadron-aligned minor faction recorded yet.")

        history = list(getattr(state, "squadron_rank_history", None) or [])
        history.sort(key=lambda h: h.get("timestamp") or "", reverse=True)
        self._history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            date_item = QTableWidgetItem(str(h.get("timestamp") or ""))
            change_item = QTableWidgetItem("Promoted" if h.get("promotion") else "Demoted")
            rank_item = QTableWidgetItem(f"{h.get('old_rank')} → {h.get('new_rank')}")
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_table.setItem(row, 0, date_item)
            self._history_table.setItem(row, 1, change_item)
            self._history_table.setItem(row, 2, rank_item)
