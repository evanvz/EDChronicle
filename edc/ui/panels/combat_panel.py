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

        # ── Combat contacts card ──────────────────────────────────────────
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #0d1520; border: 1px solid #1e2a3a;"
            "border-radius: 5px; }"
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(8, 6, 8, 6)
        card_l.setSpacing(4)

        card_hdr = QLabel("COMBAT CONTACTS")
        card_hdr.setStyleSheet(
            "color: #555555; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        card_l.addWidget(card_hdr)

        # Legend
        legend = QLabel(
            '<span style="color:#B4640A;">■</span> Current &nbsp;'
            '<span style="color:#640078;">■</span> PP Enemy &nbsp;'
            '<span style="color:#C8A000;">■</span> High Bounty &nbsp;'
            '<span style="color:#503200;">■</span> Wanted &nbsp;'
            '<span style="color:#5A1E1E;">■</span> Destroyed'
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setStyleSheet(
            "font-size: 10px; color: #888888; "
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
            "font-size: 10px; font-weight: bold; letter-spacing: 1px; "
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
            contacts = getattr(state, "combat_contacts", None) or {}
            cur_key  = getattr(state, "combat_current_key", "") or ""
            pledged  = (getattr(state, "pp_power", None) or "").strip().lower()

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

                is_enemy = bool(
                    pledged
                    and power.strip().lower()
                    and power.strip().lower() != pledged
                )
                enemy_txt = "⚔ ENEMY" if is_enemy else ""

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
                elif is_enemy:
                    bg = QColor(100, 0, 120)
                    fg = QColor(255, 200, 255)
                elif is_high_bounty:
                    bg = QColor(200, 160, 0)
                    fg = QColor(255, 255, 255)
                elif wanted_f:
                    bg = QColor(80, 50, 0)
                    fg = QColor(255, 220, 150)
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
