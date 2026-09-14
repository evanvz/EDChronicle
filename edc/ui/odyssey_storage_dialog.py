# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt


def _esc(t):
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class OdysseyStorageDialog(QDialog):
    """
    Item list for one ShipLocker storage category (Assets/Goods/
    Consumables/Data), opened by clicking that category's card on the
    Materials tab. Shows what's actually usable -- cross-referenced
    against odyssey_engineering.json's suit/weapon grade and module
    material costs -- so a raw loot dump becomes "this is for Enhanced
    Tracking" rather than an opaque list of names.
    """

    def __init__(self, category: str, state, engineering_table, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"ShipLocker — {category}")
        self.setMinimumWidth(560)
        self.setStyleSheet("QDialog { background: #0d1015; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        by_category = getattr(state, "shiplocker_by_category", {}) or {}
        items = by_category.get(category, {}) or {}
        localised = dict(getattr(state, "backpack_localised", {}) or {})
        localised.update(getattr(state, "shiplocker_localised", {}) or {})
        backpack = getattr(state, "backpack_items", {}) or {}

        usage_index = {}
        if engineering_table is not None:
            try:
                usage_index = engineering_table.materials_usage_index()
            except Exception:
                usage_index = {}

        total = sum(v for v in items.values() if isinstance(v, int))
        hdr = QLabel(
            f'<span style="color:#4da3ff;font-weight:700;font-size:14px;">'
            f'{_esc(category)}</span>'
            f'<span style="color:#888888;font-size:12px;"> — {total}/1000</span>'
        )
        hdr.setTextFormat(Qt.TextFormat.RichText)
        hdr.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(hdr)

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Item", "Qty", "In Backpack", "Used In"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(320)

        rows = []
        for key, cnt in items.items():
            if not isinstance(key, str) or not isinstance(cnt, int):
                continue
            disp = localised.get(key) or key.replace("_", " ").title()
            used_in = usage_index.get(key) or []
            rows.append((disp, cnt, backpack.get(key, 0), ", ".join(used_in) if used_in else "—"))
        rows.sort(key=lambda r: r[0].lower())

        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, (disp, cnt, in_bp, used_in) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(disp))
            table.setItem(r, 1, QTableWidgetItem(str(cnt)))
            table.setItem(r, 2, QTableWidgetItem(str(in_bp)))
            used_item = QTableWidgetItem(used_in)
            if used_in == "—":
                used_item.setForeground(Qt.GlobalColor.darkGray)
            table.setItem(r, 3, used_item)
        table.setSortingEnabled(True)

        layout.addWidget(table)
