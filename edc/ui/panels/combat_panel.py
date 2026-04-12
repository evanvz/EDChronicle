import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
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

        layout = QVBoxLayout(self)

        self.combat_hint = QLabel(
            "Scanned contacts will appear here once you "
            "fully scan a ship (ScanStage >= 3)."
        )
        self.combat_hint.setWordWrap(True)

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

        # Column resize modes
        self.combat_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch       # Pilot
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch       # Faction
        )
        for col in [1, 2, 4, 5, 6, 7, 8]:
            self.combat_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        layout.addWidget(self.combat_hint)
        layout.addWidget(self.combat_table, 1)

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

                rank      = rec.get("Rank") or ""
                ship      = rec.get("Ship") or ""
                faction   = rec.get("Faction") or ""
                power     = rec.get("Power") or ""
                wanted_f  = bool(rec.get("Wanted"))
                bounty    = rec.get("Bounty")
                bounty_txt = f"{bounty:,}" if isinstance(bounty, int) else ""

                ts = rec.get("LastSeen") or ""
                if isinstance(ts, str) and "T" in ts:
                    last_seen = ts.split("T", 1)[1].replace("Z", "")[:8]
                else:
                    last_seen = str(ts) if ts else ""

                # Derive enemy status
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
                    QTableWidgetItem(str(pilot)),       # 0
                    QTableWidgetItem(str(rank)),        # 1
                    QTableWidgetItem(str(ship)),        # 2
                    QTableWidgetItem(str(faction)),     # 3
                    QTableWidgetItem(str(power)),       # 4
                    QTableWidgetItem(enemy_txt),        # 5 — Enemy
                    QTableWidgetItem("Wanted" if wanted_f else ""),  # 6
                    QTableWidgetItem(bounty_txt),       # 7
                    QTableWidgetItem(last_seen),        # 8
                ]
                items[0].setData(Qt.ItemDataRole.UserRole, k)

                # Row colour priority:
                # 1. Destroyed — dark red
                # 2. Current scan target — orange (highest visibility)
                # 3. Enemy PP — purple
                # 4. High bounty — gold
                # 5. Wanted — dark amber
                is_current = bool(cur_key and k == cur_key)

                if destroyed:
                    bg = QColor(90, 30, 30)
                    fg = QColor(255, 220, 220)
                elif is_current:
                    bg = QColor(180, 100, 0)    # orange
                    fg = QColor(255, 255, 255)
                elif is_enemy:
                    bg = QColor(100, 0, 120)    # purple
                    fg = QColor(255, 200, 255)
                elif is_high_bounty:
                    bg = QColor(200, 160, 0)    # gold
                    fg = QColor(255, 255, 255)
                elif wanted_f:
                    bg = QColor(80, 50, 0)      # dark amber
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
