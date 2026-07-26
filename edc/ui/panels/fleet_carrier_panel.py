"""Fleet Carrier status panel — fuel, finance, docking access, trade orders."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
)


class FleetCarrierPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Fleet Carrier tab.
    Receives state via refresh(state). Knows nothing about
    main_window or repo.
    """

    _CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
    _HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
    _LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Status card ───────────────────────────────────────────────────
        status_frame = QFrame()
        status_frame.setStyleSheet(self._CARD_STYLE)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(8, 6, 8, 8)
        status_layout.setSpacing(4)

        hdr = QLabel("FLEET CARRIER")
        hdr.setStyleSheet(self._HDR_STYLE)
        status_layout.addWidget(hdr)

        self._name_label = QLabel("No fleet carrier detected.")
        self._name_label.setWordWrap(True)
        self._name_label.setStyleSheet(self._LABEL_STYLE + " font-weight:bold; font-size:13px;")
        status_layout.addWidget(self._name_label)

        row1 = QHBoxLayout()
        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(self._LABEL_STYLE)
        self._fuel_label = QLabel("Fuel: —")
        self._fuel_label.setStyleSheet(self._LABEL_STYLE)
        self._docking_label = QLabel("Docking: —")
        self._docking_label.setStyleSheet(self._LABEL_STYLE)
        row1.addWidget(self._location_label)
        row1.addWidget(self._fuel_label)
        row1.addWidget(self._docking_label)
        row1.addStretch()
        status_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._jump_range_label = QLabel("Jump range: —")
        self._jump_range_label.setStyleSheet(self._LABEL_STYLE)
        self._space_label = QLabel("Free space: —")
        self._space_label.setStyleSheet(self._LABEL_STYLE)
        row2.addWidget(self._jump_range_label)
        row2.addWidget(self._space_label)
        row2.addStretch()
        status_layout.addLayout(row2)

        self._next_jump_label = QLabel("")
        self._next_jump_label.setStyleSheet("color:#FFB347; background:transparent; border:none;")
        self._next_jump_label.setVisible(False)
        status_layout.addWidget(self._next_jump_label)

        root.addWidget(status_frame)

        # ── Finance card ──────────────────────────────────────────────────
        fin_frame = QFrame()
        fin_frame.setStyleSheet(self._CARD_STYLE)
        fin_layout = QVBoxLayout(fin_frame)
        fin_layout.setContentsMargins(8, 6, 8, 8)
        fin_layout.setSpacing(4)

        fin_hdr = QLabel("FINANCE")
        fin_hdr.setStyleSheet(self._HDR_STYLE)
        fin_layout.addWidget(fin_hdr)

        self._finance_label = QLabel("—")
        self._finance_label.setWordWrap(True)
        self._finance_label.setStyleSheet(self._LABEL_STYLE)
        fin_layout.addWidget(self._finance_label)

        root.addWidget(fin_frame)

        # ── Trade orders table ────────────────────────────────────────────
        orders_hdr = QLabel("TRADE ORDERS")
        orders_hdr.setStyleSheet(self._HDR_STYLE)
        root.addWidget(orders_hdr)

        self._orders_table = QTableWidget()
        self._orders_table.setColumnCount(4)
        self._orders_table.setHorizontalHeaderLabels(["Commodity", "Buy Qty", "Sell Stock", "Price"])
        self._orders_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._orders_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._orders_table.verticalHeader().setVisible(False)
        self._orders_table.setAlternatingRowColors(True)
        self._orders_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
        )
        h = self._orders_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._orders_table, 1)

    def refresh(self, state) -> None:
        callsign = getattr(state, "carrier_callsign", None)
        if not callsign:
            self._name_label.setText("No fleet carrier detected.")
            self._location_label.setText("Location: —")
            self._fuel_label.setText("Fuel: —")
            self._docking_label.setText("Docking: —")
            self._jump_range_label.setText("Jump range: —")
            self._space_label.setText("Free space: —")
            self._next_jump_label.setVisible(False)
            self._finance_label.setText("—")
            self._orders_table.setRowCount(0)
            return

        name = getattr(state, "carrier_name", None) or ""
        self._name_label.setText(f"{name} ({callsign})" if name else callsign)

        location = getattr(state, "carrier_current_system", None) or "—"
        self._location_label.setText(f"Location: {location}")

        fuel = getattr(state, "carrier_fuel_level", None)
        self._fuel_label.setText(f"Fuel: {fuel} t" if isinstance(fuel, int) else "Fuel: —")

        docking = getattr(state, "carrier_docking_access", None) or "—"
        self._docking_label.setText(f"Docking: {docking.title() if isinstance(docking, str) else docking}")

        curr = getattr(state, "carrier_jump_range_curr", None)
        maxr = getattr(state, "carrier_jump_range_max", None)
        if isinstance(curr, float) and isinstance(maxr, float):
            self._jump_range_label.setText(f"Jump range: {curr:.1f} / {maxr:.1f} ly")
        else:
            self._jump_range_label.setText("Jump range: —")

        space = getattr(state, "carrier_space_usage", {}) or {}
        free = space.get("FreeSpace")
        total = space.get("TotalCapacity")
        if isinstance(free, int) and isinstance(total, int):
            self._space_label.setText(f"Free space: {free:,} / {total:,} t")
        else:
            self._space_label.setText("Free space: —")

        next_system = getattr(state, "carrier_next_jump_system", None)
        if next_system:
            self._next_jump_label.setText(f"Jump scheduled: {next_system}")
            self._next_jump_label.setVisible(True)
        else:
            self._next_jump_label.setVisible(False)

        finance = getattr(state, "carrier_finance", {}) or {}
        if finance:
            parts = []
            if isinstance(finance.get("CarrierBalance"), int):
                parts.append(f"Balance: {finance['CarrierBalance']:,} cr")
            if isinstance(finance.get("ReserveBalance"), int):
                parts.append(f"Reserve: {finance['ReserveBalance']:,} cr")
            if isinstance(finance.get("AvailableBalance"), int):
                parts.append(f"Available: {finance['AvailableBalance']:,} cr")
            if isinstance(finance.get("TaxRate"), int):
                parts.append(f"Tax rate: {finance['TaxRate']}%")
            self._finance_label.setText(" | ".join(parts) if parts else "—")
        else:
            self._finance_label.setText("—")

        orders = getattr(state, "carrier_trade_orders", {}) or {}
        rows = list(orders.values())
        self._orders_table.setRowCount(len(rows))
        for r, order in enumerate(rows):
            name_item = QTableWidgetItem(order.get("commodity_localised") or order.get("commodity") or "")
            buy_item = QTableWidgetItem(str(order.get("purchase_order")) if order.get("purchase_order") is not None else "—")
            sell_item = QTableWidgetItem(str(order.get("sale_order")) if order.get("sale_order") is not None else "—")
            price_item = QTableWidgetItem(f"{order['price']:,}" if isinstance(order.get("price"), int) else "—")
            for it in (buy_item, sell_item, price_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._orders_table.setItem(r, 0, name_item)
            self._orders_table.setItem(r, 1, buy_item)
            self._orders_table.setItem(r, 2, sell_item)
            self._orders_table.setItem(r, 3, price_item)
