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
        self.combat_table.setColumnCount(8)
        self.combat_table.setHorizontalHeaderLabels(
            ["Pilot", "Rank", "Ship", "Faction",
             "Power", "Wanted", "Bounty", "Last Seen"]
        )
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
        self.combat_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.ResizeMode.ResizeToContents
        )
        self.combat_table.setMinimumHeight(120)

        layout.addWidget(self.combat_hint)
        layout.addWidget(self.combat_table, 1)

    def refresh(self, state):
        try:
            contacts = getattr(state, "combat_contacts", None) or {}
            cur_key = getattr(state, "combat_current_key", "") or ""
            pledged = getattr(state, "pp_power", None)

            rows = []
            for k, rec in contacts.items():
                if isinstance(rec, dict):
                    rows.append((k, rec))

            def _ts(rec):
                ts = rec.get("LastSeen") or ""
                return ts if isinstance(ts, str) else ""

            rows.sort(key=lambda x: _ts(x[1]), reverse=True)

            self.combat_table.setSortingEnabled(False)
            self.combat_table.setRowCount(len(rows))

            selected_row = None
            for r, (k, rec) in enumerate(rows):
                pilot = rec.get("Pilot") or ""
                destroyed = bool(rec.get("Destroyed"))
                if destroyed and pilot:
                    pilot = f"{pilot} [DESTROYED]"
                rank = rec.get("Rank") or ""
                ship = rec.get("Ship") or ""
                faction = rec.get("Faction") or ""
                power = rec.get("Power") or ""
                wanted_flag = bool(rec.get("Wanted"))
                wanted = "Wanted" if wanted_flag else ""
                bounty = rec.get("Bounty")
                bounty_txt = (
                    f"{bounty:,}" if isinstance(bounty, int) else ""
                )

                ts = rec.get("LastSeen") or ""
                if isinstance(ts, str) and "T" in ts:
                    last_seen = ts.split("T", 1)[1].replace("Z", "")[:8]
                else:
                    last_seen = str(ts) if ts else ""

                items = [
                    QTableWidgetItem(str(pilot)),
                    QTableWidgetItem(str(rank)),
                    QTableWidgetItem(str(ship)),
                    QTableWidgetItem(str(faction)),
                    QTableWidgetItem(str(power)),
                    QTableWidgetItem(str(wanted)),
                    QTableWidgetItem(str(bounty_txt)),
                    QTableWidgetItem(str(last_seen)),
                ]
                items[0].setData(Qt.ItemDataRole.UserRole, k)

                is_pp_enemy = bool(
                    pledged and power and power != pledged
                )
                is_high_bounty = bool(
                    wanted_flag
                    and isinstance(bounty, int)
                    and bounty >= 500000
                    and str(rank).lower() in {
                        "dangerous", "deadly", "elite"
                    }
                )

                highlight = None
                foreground = None
                if destroyed:
                    highlight = QColor(90, 30, 30)
                    foreground = QColor(255, 220, 220)
                elif is_pp_enemy:
                    highlight = QColor(170, 0, 170)
                    foreground = QColor(255, 255, 255)
                elif is_high_bounty:
                    highlight = QColor(200, 160, 0)
                    foreground = QColor(255, 255, 255)

                if highlight:
                    for it in items:
                        it.setBackground(highlight)
                        if foreground:
                            it.setForeground(foreground)

                for c, it in enumerate(items):
                    self.combat_table.setItem(r, c, it)

                if cur_key and k == cur_key:
                    selected_row = r

            self.combat_table.setSortingEnabled(True)
            if selected_row is not None:
                self.combat_table.selectRow(selected_row)

        except Exception:
            log.exception("CombatPanel.refresh failed")