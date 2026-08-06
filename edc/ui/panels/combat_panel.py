import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from edc.core.bgs_conflicts import find_squadron_war_enemy

log = logging.getLogger(__name__)


class CombatPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Combat tab.
    Receives state via refresh(state). Knows nothing about
    main_window, repo, or any other panel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header strip ──────────────────────────────────────────────────
        hdr = QWidget()
        hdr_l = QVBoxLayout(hdr)
        hdr_l.setContentsMargins(8, 6, 8, 4)
        hdr_l.setSpacing(2)

        self.combat_hint = QLabel(
            "Scanned contacts will appear here once you "
            "fully scan a ship (ScanStage >= 3)."
        )
        self.combat_hint.setWordWrap(True)
        hdr_l.addWidget(self.combat_hint)
        outer.addWidget(hdr, 0)

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_l = QVBoxLayout(content)
        content_l.setSpacing(6)
        content_l.setContentsMargins(8, 6, 8, 8)
        content_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        # ── Notoriety card (always visible — distinct from bounties, can't
        # be paid off, only decays with active play) ───────────────────────
        self.notoriety_card = QFrame()
        self.notoriety_card.setStyleSheet(
            "QFrame { background: #201a0d; border: 1px solid #4a3a1e;"
            "border-radius: 5px; }"
        )
        notoriety_l = QVBoxLayout(self.notoriety_card)
        notoriety_l.setContentsMargins(8, 6, 8, 6)
        notoriety_l.setSpacing(4)

        notoriety_hdr = QLabel("NOTORIETY")
        notoriety_hdr.setStyleSheet(
            "color: #d0a060; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        notoriety_l.addWidget(notoriety_hdr)

        self.notoriety_summary = QLabel("")
        self.notoriety_summary.setWordWrap(True)
        self.notoriety_summary.setStyleSheet(
            "color: #cccccc; font-size: 12px; background: transparent; border: none;"
        )
        notoriety_l.addWidget(self.notoriety_summary)

        content_l.addWidget(self.notoriety_card)

        # ── Bounty clearance card (hidden unless a bounty is active) ──────
        self.bounty_card = QFrame()
        self.bounty_card.setStyleSheet(
            "QFrame { background: #2a0a0a; border: 1px solid #4a1e1e;"
            "border-radius: 5px; }"
        )
        bounty_l = QVBoxLayout(self.bounty_card)
        bounty_l.setContentsMargins(8, 6, 8, 6)
        bounty_l.setSpacing(4)

        bounty_hdr = QLabel("BOUNTY CLEARANCE")
        bounty_hdr.setStyleSheet(
            "color: #d06060; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        bounty_l.addWidget(bounty_hdr)

        self.bounty_summary = QLabel("")
        self.bounty_summary.setWordWrap(True)
        self.bounty_summary.setStyleSheet(
            "color: #ffcccc; font-size: 12px; background: transparent; border: none;"
        )
        bounty_l.addWidget(self.bounty_summary)

        self.bounty_station = QLabel("")
        self.bounty_station.setWordWrap(True)
        self.bounty_station.setStyleSheet(
            "color: #cccccc; font-size:12px; background: transparent; border: none;"
        )
        bounty_l.addWidget(self.bounty_station)

        content_l.addWidget(self.bounty_card)
        self.bounty_card.setVisible(False)

        # ── Massacre mission stacking card (hidden if no massacre missions
        # currently active) ────────────────────────────────────────────────
        self.massacre_card = QFrame()
        self.massacre_card.setStyleSheet(
            "QFrame { background: #1a0d0d; border: 1px solid #4a1e1e;"
            "border-radius: 5px; }"
        )
        massacre_l = QVBoxLayout(self.massacre_card)
        massacre_l.setContentsMargins(8, 6, 8, 6)
        massacre_l.setSpacing(4)

        massacre_hdr = QLabel("MASSACRE MISSIONS")
        massacre_hdr.setStyleSheet(
            "color: #d06060; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        massacre_l.addWidget(massacre_hdr)

        self.massacre_table = QTableWidget()
        self.massacre_table.setColumnCount(5)
        self.massacre_table.setHorizontalHeaderLabels(
            ["Target Faction", "System", "Kills", "Stacked", "Status"]
        )
        self.massacre_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.massacre_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.massacre_table.verticalHeader().setVisible(False)
        self.massacre_table.setSortingEnabled(False)
        self.massacre_table.setStyleSheet(
            "QTableWidget { background: transparent; border: none; }"
            "QHeaderView::section { background: #2a1a1a; color: #888888; "
            "font-size:12px; font-weight: bold; letter-spacing: 1px; "
            "border: none; padding: 4px; }"
        )
        self.massacre_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.massacre_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for col in [2, 3, 4]:
            self.massacre_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        massacre_l.addWidget(self.massacre_table)

        content_l.addWidget(self.massacre_card)
        self.massacre_card.setVisible(False)

        # ── Combat contacts card ──────────────────────────────────────────
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(8, 6, 8, 6)
        card_l.setSpacing(4)

        card_hdr = QLabel("COMBAT CONTACTS")
        card_hdr.setStyleSheet(
            "color: #555555; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        card_l.addWidget(card_hdr)

        # Legend
        legend = QLabel(
            '<span style="color:#B4640A;">■</span> Current &nbsp;'
            '<span style="color:#D42A00;">■</span> Hostile (confirmed safe target) &nbsp;'
            '<span style="color:#640078;">■</span> PP Enemy &nbsp;'
            '<span style="color:#C8A000;">■</span> High Bounty &nbsp;'
            '<span style="color:#503200;">■</span> Wanted &nbsp;'
            '<span style="color:#5A1E1E;">■</span> Destroyed &nbsp;'
            '<span style="color:#5A2A2A;">■</span> At war (info only, not confirmed)'
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setStyleSheet(
            "font-size:12px; color: #888888; "
            "background: transparent; border: none;"
        )
        card_l.addWidget(legend)

        self.combat_table = QTableWidget()
        self.combat_table.setColumnCount(9)
        self.combat_table.setHorizontalHeaderLabels([
            "Pilot", "Rank", "Ship", "Faction",
            "Power", "Enemy", "Wanted", "Bounty", "Last Seen"
        ])
        self.combat_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.combat_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.combat_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.combat_table.verticalHeader().setVisible(False)
        self.combat_table.setSortingEnabled(False)
        self.combat_table.setMinimumHeight(120)
        self.combat_table.setStyleSheet(
            "QTableWidget { background: transparent; border: none; }"
            "QHeaderView::section { background: #1a2a3a; color: #888888; "
            "font-size:12px; font-weight: bold; letter-spacing: 1px; "
            "border: none; padding: 4px; }"
        )

        self.combat_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        for col in [1, 2, 4, 5, 6, 7, 8]:
            self.combat_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        card_l.addWidget(self.combat_table)
        content_l.addWidget(card)

    def refresh(self, state):
        try:
            self._refresh_notoriety_card(state)
        except Exception:
            log.exception("CombatPanel._refresh_notoriety_card failed")

        try:
            self._refresh_bounty_card(state)
        except Exception:
            log.exception("CombatPanel._refresh_bounty_card failed")

        try:
            self._refresh_massacre_card(state)
        except Exception:
            log.exception("CombatPanel._refresh_massacre_card failed")

        try:
            contacts = getattr(state, "combat_contacts", None) or {}
            cur_key  = getattr(state, "combat_current_key", "") or ""
            pledged  = (getattr(state, "pp_power", None) or "").strip().lower()
            war_enemy_faction = find_squadron_war_enemy(
                getattr(state, "factions", None), getattr(state, "system_conflicts", None)
            )

            rows = []
            for k, rec in contacts.items():
                if isinstance(rec, dict):
                    rows.append((k, rec))

            rows.sort(
                key=lambda x: x[1].get("LastSeen") or "",
                reverse=True
            )

            self.combat_table.setSortingEnabled(False)
            self.combat_table.setRowCount(len(rows))

            selected_row = None

            for r, (k, rec) in enumerate(rows):
                pilot     = rec.get("Pilot") or ""
                destroyed = bool(rec.get("Destroyed"))
                if destroyed and pilot:
                    pilot = f"{pilot} [DESTROYED]"

                rank       = rec.get("Rank") or ""
                ship       = rec.get("Ship") or ""
                faction    = rec.get("Faction") or ""
                power      = rec.get("Power") or ""
                wanted_f   = bool(rec.get("Wanted"))
                bounty     = rec.get("Bounty")
                bounty_txt = f"{bounty:,}" if isinstance(bounty, int) else ""

                ts = rec.get("LastSeen") or ""
                if isinstance(ts, str) and "T" in ts:
                    last_seen = ts.split("T", 1)[1].replace("Z", "")[:8]
                else:
                    last_seen = str(ts) if ts else ""

                is_hostile = bool(rec.get("Hostile"))
                is_enemy = bool(
                    pledged
                    and power.strip().lower()
                    and power.strip().lower() != pledged
                )
                # Informational only — a faction being at war with your
                # squadron faction doesn't make an arbitrary Clean NPC from
                # that faction a legal kill; only LegalStatus "Hostile"
                # (confirmed via Conflict Zone engagement) actually is.
                bgs_war_faction_match = bool(
                    war_enemy_faction and faction and faction == war_enemy_faction
                )
                if is_hostile:
                    enemy_txt = "⚔ HOSTILE"
                elif is_enemy:
                    enemy_txt = "⚔ PP ENEMY"
                elif bgs_war_faction_match:
                    enemy_txt = "⚠ at war (info)"
                else:
                    enemy_txt = ""

                is_high_bounty = bool(
                    wanted_f
                    and isinstance(bounty, int)
                    and bounty >= 500_000
                    and str(rank).lower() in {"dangerous", "deadly", "elite"}
                )

                items = [
                    QTableWidgetItem(str(pilot)),
                    QTableWidgetItem(str(rank)),
                    QTableWidgetItem(str(ship)),
                    QTableWidgetItem(str(faction)),
                    QTableWidgetItem(str(power)),
                    QTableWidgetItem(enemy_txt),
                    QTableWidgetItem("Wanted" if wanted_f else ""),
                    QTableWidgetItem(bounty_txt),
                    QTableWidgetItem(last_seen),
                ]
                items[0].setData(Qt.ItemDataRole.UserRole, k)

                is_current = bool(cur_key and k == cur_key)

                if destroyed:
                    bg = QColor(90, 30, 30)
                    fg = QColor(255, 220, 220)
                elif is_current:
                    bg = QColor(180, 100, 0)
                    fg = QColor(255, 255, 255)
                elif is_hostile:
                    bg = QColor(212, 42, 0)
                    fg = QColor(255, 255, 255)
                elif is_enemy:
                    bg = QColor(100, 0, 120)
                    fg = QColor(255, 200, 255)
                elif is_high_bounty:
                    bg = QColor(200, 160, 0)
                    fg = QColor(255, 255, 255)
                elif wanted_f:
                    bg = QColor(80, 50, 0)
                    fg = QColor(255, 220, 150)
                elif bgs_war_faction_match:
                    bg = QColor(70, 30, 30)
                    fg = QColor(220, 180, 180)
                else:
                    bg = None
                    fg = None

                for c, it in enumerate(items):
                    if bg:
                        it.setBackground(bg)
                    if fg:
                        it.setForeground(fg)
                    self.combat_table.setItem(r, c, it)

                if is_current:
                    selected_row = r

            self.combat_table.setSortingEnabled(True)
            if selected_row is not None:
                self.combat_table.selectRow(selected_row)

        except Exception:
            log.exception("CombatPanel.refresh failed")

    def _refresh_notoriety_card(self, state):
        notoriety = getattr(state, "notoriety", None)
        ts = getattr(state, "notoriety_timestamp", None) or "unknown"

        if notoriety is None:
            self.notoriety_summary.setText("No reading yet — open the in-game Statistics panel once to record it.")
            return

        if notoriety <= 0:
            self.notoriety_summary.setText(f"Clean (as of {ts}).")
            return

        min_hours = notoriety * 2
        self.notoriety_summary.setText(
            f"Level {notoriety} (as of {ts}). Decays 1 point per 2 hours of active "
            f"in-game time (paused at the main menu) — at least {min_hours}h of "
            f"continuous play from that reading to fully clear. Can't be paid off."
        )

    def _refresh_bounty_card(self, state):
        active = getattr(state, "active_bounties", None) or {}
        if not active:
            self.bounty_card.setVisible(False)
            return

        self.bounty_card.setVisible(True)
        parts = [f"{faction}: {amount:,} Cr" for faction, amount in active.items()]
        self.bounty_summary.setText("Outstanding: " + "  |  ".join(parts))

        station = getattr(state, "closest_interstellar_factors", None)
        if not isinstance(station, dict):
            self.bounty_station.setText(
                "No confirmed Interstellar Factors station known yet — "
                "dock somewhere offering it to record it."
            )
            return

        dist = station.get("distance_ly")
        dist_txt = f"{dist:.1f} ly" if isinstance(dist, (int, float)) else "? ly"
        last_visited = station.get("last_visited") or "unknown date"
        pad_size = station.get("pad_size") or "?"
        pad_txt = f"{pad_size} pad" if pad_size != "?" else "pad size unknown"
        self.bounty_station.setText(
            f"Closest known: {station.get('station_name') or '?'} "
            f"({station.get('system_name') or '?'}), {dist_txt}, {pad_txt} — "
            f"controlled by {station.get('station_faction') or 'unknown faction'}. "
            f"Confirmed as of {last_visited} — Interstellar Factors availability "
            f"shifts with system security/BGS, so verify on arrival."
        )

    def _refresh_massacre_card(self, state):
        active = getattr(state, "active_missions", None) or {}
        rows = [rec for rec in active.values() if isinstance(rec.get("kill_count"), int) and rec["kill_count"] > 0]
        if not rows:
            self.massacre_card.setVisible(False)
            return
        self.massacre_card.setVisible(True)

        stack_counts = {}
        for rec in rows:
            key = (rec.get("target_faction"), rec.get("destination_system"))
            stack_counts[key] = stack_counts.get(key, 0) + 1

        rows.sort(key=lambda r: (r.get("target_faction") or "", r.get("destination_system") or ""))

        self.massacre_table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            target = rec.get("target_faction") or "?"
            system = rec.get("destination_system") or "?"
            credited = rec.get("kills_credited", 0)
            needed = rec["kill_count"]
            stacked = stack_counts[(rec.get("target_faction"), rec.get("destination_system"))]
            ready = credited >= needed
            status = "Ready to turn in" if ready else ""

            self.massacre_table.setItem(r, 0, QTableWidgetItem(target))
            self.massacre_table.setItem(r, 1, QTableWidgetItem(system))
            self.massacre_table.setItem(r, 2, QTableWidgetItem(f"{credited}/{needed}"))
            self.massacre_table.setItem(r, 3, QTableWidgetItem(str(stacked) if stacked > 1 else "-"))
            status_item = QTableWidgetItem(status)
            if ready:
                status_item.setForeground(QColor("#60d060"))
            self.massacre_table.setItem(r, 4, status_item)
