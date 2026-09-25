# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Session BGS Activity Report — read-only window showing every faction's
mission/combat/CZ/trade activity, grouped by system, since the last
detected BGS tick, across every system visited — not scoped to one
target faction the way the Faction Expansion tracker is (that one stays
exactly as-is; this is a different question, "what did I do this
session" vs. "is my one targeted push working").

Session boundary reuses PlayerFactionPanel._latest_known_tick (already
kept fresh by main_window.py's _BgsTickCheckWorker timer) rather than
fetching the tick itself -- no new network code needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QFrame,
)

from edc.ui.style import CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE
from edc.ui import formatting as fmt

log = logging.getLogger("edc.session_activity")

# Same palette player_faction_panel.py uses for faction identity coloring
# (_FACTION_CHART_COLORS) -- duplicated as a short color list rather than
# imported, since that module imports SessionActivityDialog from here and
# importing back would be circular.
_FACTION_COLORS = [
    "#4D96FF", "#FFB347", "#6BCB77", "#FF6B6B",
    "#B983FF", "#FFD93D", "#4DD8C8", "#FF8FB1",
]

# Stat-chip colors, matching this app's existing semantic conventions
# elsewhere (green = mission/BGS INF progress, orange = credits/combat,
# red = kills, teal = trade) rather than inventing a new palette.
_CHIP_MISSIONS = "#6BCB77"
_CHIP_COMBAT = "#FF6B6B"
_CHIP_TRADE = "#4DD8C8"


class SessionActivityDialog(QDialog):
    """Non-modal window: whole-session, all-faction BGS activity report."""

    def __init__(self, panel: "PlayerFactionPanel"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self.setWindowTitle("Session BGS Activity Report")
        self.resize(700, 600)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel("SESSION ACTIVITY — SINCE LAST BGS TICK")
        hdr.setStyleSheet(_HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        self._tick_label = QLabel("")
        self._tick_label.setStyleSheet("background:transparent; border:none; color:#888888; font-size:11px;")
        layout.addWidget(self._tick_label)

        # ── Scroll area of per-system cards -- same pattern combat_panel.py/
        # exploration_panel.py/etc already use, rather than a single plain-
        # text dump. ──────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

        self._empty_label = QLabel("No activity recorded yet this session.")
        self._empty_label.setStyleSheet("background:transparent; border:none; color:#666666;")
        self._empty_label.setVisible(False)
        self._content_layout.addWidget(self._empty_label)
        self._cards: list = []
        self._day_headers: list = []

    def _clear_cards(self) -> None:
        for w in self._cards + self._day_headers:
            self._content_layout.removeWidget(w)
            w.deleteLater()
        self._cards = []
        self._day_headers = []

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        tick_iso = getattr(self._panel, "_latest_known_tick", None)
        if not tick_iso:
            self._tick_label.setText("No BGS tick detected yet this session — showing all recorded activity.")
            since = "1970-01-01T00:00:00Z"
        else:
            age_txt, _ = fmt.relative_time(tick_iso)
            self._tick_label.setText(f"Since last tick: {age_txt}")
            since = tick_iso

        try:
            report = self._panel._repo.get_session_activity_report(since)
        except Exception:
            log.exception("Failed to load session activity report")
            report = {}
        self._render_report(report)

    @staticmethod
    def _format_chips(entry: dict) -> str:
        """One compact, color-coded rich-text line per faction -- BGS-Tally-
        style stat chips (.INF/.CBs/.GroundCZs/.Sold) instead of a verbose
        sentence. Only categories with actual activity are shown, same as
        BGS-Tally's own report."""
        chips = []

        m = entry["missions"]
        if m["count"]:
            chips.append(
                f'<span style="color:{_CHIP_MISSIONS};">.INF</span> {m["weighted"]:+d} '
                f'({m["count"]}m: {m["primary_count"]}p/{m["secondary_count"]}s)'
            )

        if entry["combat_bonds_total"]:
            chips.append(f'<span style="color:{_CHIP_COMBAT};">.CBs</span> {entry["combat_bonds_total"]:,}')

        cz = entry["cz_kills"]
        cz_parts = [f"{v}x{k.replace('_', '')}" for k, v in cz.items() if v]
        if cz_parts:
            chips.append(f'<span style="color:{_CHIP_COMBAT};">.CZs</span> {" ".join(cz_parts)}')

        trade = entry["trade_sold"]
        trade_parts = [f"{k}: {v:,}" for k, v in trade.items() if v]
        if trade_parts:
            chips.append(f'<span style="color:{_CHIP_TRADE};">.Sold</span> {", ".join(trade_parts)}')

        return "  ".join(chips) if chips else '<span style="color:#555555;">no activity</span>'

    @staticmethod
    def _format_mission_types(entry: dict) -> str:
        """Dim sub-line breaking mission count down by kind, with each
        kind's total CR reward (e.g. "Courier x2 (48,200 CR), Massacre
        Conflict CivilWar x1 (312,000 CR)") -- not every mission is
        INF-driven, so the credit payout matters on its own, not just as a
        proxy for influence_tier. Reward is only ever summed from a
        mission's is_primary row (see get_session_activity_report), so a
        secondary effect in another system doesn't double it. From the
        journal's own Name field cleaned at write time -- see
        main_window.py's _record_faction_mission_completion. Empty string
        when there are no missions or none carry a recorded type (rows
        written before this column existed)."""
        m = entry["missions"]
        by_type = m.get("by_type") or {}
        reward_by_type = m.get("reward_by_type") or {}
        parts = []
        for t, c in sorted(by_type.items(), key=lambda kv: -kv[1]):
            reward = reward_by_type.get(t, 0)
            reward_txt = f" ({reward:,} CR)" if reward else ""
            parts.append(f"{t} x{c}{reward_txt}")
        return ", ".join(parts)

    @staticmethod
    def _format_day_header(date_str: str) -> str:
        """"Today — 2026-09-25" / "Yesterday — 2026-09-24" / "Wednesday —
        2026-09-23" -- a tick delayed past 24h can make one "since last
        tick" window span more than one calendar day, so each day gets its
        own labeled section rather than one flat total."""
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return date_str
        delta = (datetime.now(timezone.utc).date() - d).days
        if delta == 0:
            return f"Today — {date_str}"
        if delta == 1:
            return f"Yesterday — {date_str}"
        return f"{d.strftime('%A')} — {date_str}"

    def _render_report(self, report: dict) -> None:
        self._clear_cards()
        self._empty_label.setVisible(not report)
        if not report:
            return

        for date_str in sorted(report.keys(), reverse=True):  # most recent day first
            day_hdr = QLabel(self._format_day_header(date_str))
            day_hdr.setStyleSheet(_HDR_STYLE + " font-size:15px;")
            self._content_layout.addWidget(day_hdr)
            self._day_headers.append(day_hdr)

            systems = report[date_str]
            for system_name in sorted(systems.keys()):
                card = QFrame()
                card.setStyleSheet(_CARD_STYLE)
                card_l = QVBoxLayout(card)
                card_l.setContentsMargins(8, 6, 8, 8)
                card_l.setSpacing(4)

                hdr = QLabel(system_name)
                hdr.setStyleSheet(_HDR_STYLE)
                card_l.addWidget(hdr)

                factions = systems[system_name]
                for i, faction_name in enumerate(sorted(factions.keys())):
                    entry = factions[faction_name]
                    color = _FACTION_COLORS[i % len(_FACTION_COLORS)]
                    row = QLabel(
                        f'<span style="color:{color}; font-weight:700;">[{faction_name}]</span> '
                        f'{self._format_chips(entry)}'
                    )
                    row.setTextFormat(Qt.TextFormat.RichText)
                    row.setWordWrap(True)
                    row.setStyleSheet("background:transparent; border:none;")
                    card_l.addWidget(row)

                    mission_types = self._format_mission_types(entry)
                    if mission_types:
                        types_row = QLabel(f"    {mission_types}")
                        types_row.setWordWrap(True)
                        types_row.setStyleSheet("background:transparent; border:none; color:#666666; font-size:11px;")
                        card_l.addWidget(types_row)

                self._content_layout.addWidget(card)
                self._cards.append(card)
