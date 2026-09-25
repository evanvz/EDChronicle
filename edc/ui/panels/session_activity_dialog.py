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

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

from edc.ui.style import HDR_STYLE as _HDR_STYLE
from edc.ui import formatting as fmt

log = logging.getLogger("edc.session_activity")


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

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setStyleSheet("background:#0d1520; border:1px solid #223; color:#c8c8c8;")
        layout.addWidget(self._body, 1)

    def _set_body_text(self, text: str) -> None:
        self._body.setPlainText(text)

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

    def _render_report(self, report: dict) -> None:
        if not report:
            self._set_body_text("No activity recorded yet this session.")
            return

        lines = []
        for system_name in sorted(report.keys()):
            lines.append(f"=== {system_name} ===")
            factions = report[system_name]
            for faction_name in sorted(factions.keys()):
                entry = factions[faction_name]
                lines.append(f"  [{faction_name}]")
                m = entry["missions"]
                if m["count"]:
                    lines.append(
                        f"    Missions: {m['count']} (weight {m['weighted']}) — "
                        f"{m['primary_count']} primary / {m['secondary_count']} secondary"
                    )
                if entry["combat_bonds_total"]:
                    lines.append(f"    Combat bonds: {entry['combat_bonds_total']:,}")
                cz = entry["cz_kills"]
                cz_total = sum(cz.values())
                if cz_total:
                    parts = [f"{v}x {k}" for k, v in cz.items() if v]
                    lines.append(f"    CZ kills: {', '.join(parts)}")
                trade = entry["trade_sold"]
                trade_total = sum(trade.values())
                if trade_total:
                    parts = [f"{k}: {v:,}" for k, v in trade.items() if v]
                    lines.append(f"    Sold: {', '.join(parts)}")
            lines.append("")

        self._set_body_text("\n".join(lines))
