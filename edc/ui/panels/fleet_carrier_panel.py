"""Fleet Carrier status panel — fuel, finance, docking access, trade orders."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from edc.ui.style import CARD_STYLE, HDR_STYLE, LABEL_STYLE, set_table_empty_message as _empty, set_table_rows as _rows


class FleetCarrierPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Fleet Carrier tab.
    Receives state via refresh(state). Knows nothing about
    main_window or repo.
    """

    _CARD_STYLE = CARD_STYLE
    _HDR_STYLE = HDR_STYLE
    _LABEL_STYLE = LABEL_STYLE

    # Squadron carrier gets its own accent (purple — matches the "PP Enemy"/
    # not-exclusively-yours tone already used on the Combat tab) so it reads
    # as clearly distinct from your own carrier's card at a glance.
    _SQUAD_CARD_STYLE = "QFrame { background:#1a0d1f; border:1px solid #4a1e5a; border-radius:5px; }"
    _SQUAD_HDR_STYLE = "color:#b380d9; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"

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
        self._fuel_label = QLabel("Fuel (Tritium): —")
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

        # ── Squadron carrier card (separate from your own) ─────────────────
        squad_frame = QFrame()
        squad_frame.setStyleSheet(self._SQUAD_CARD_STYLE)
        squad_layout = QVBoxLayout(squad_frame)
        squad_layout.setContentsMargins(8, 6, 8, 8)
        squad_layout.setSpacing(4)

        squad_hdr = QLabel("SQUADRON CARRIER")
        squad_hdr.setStyleSheet(self._SQUAD_HDR_STYLE)
        squad_layout.addWidget(squad_hdr)

        self._squad_name_label = QLabel("No squadron carrier data recorded yet.")
        self._squad_name_label.setWordWrap(True)
        self._squad_name_label.setStyleSheet(self._LABEL_STYLE + " font-weight:bold; font-size:13px;")
        squad_layout.addWidget(self._squad_name_label)

        squad_row1 = QHBoxLayout()
        self._squad_location_label = QLabel("Location: —")
        self._squad_location_label.setStyleSheet(self._LABEL_STYLE)
        self._squad_fuel_label = QLabel("Fuel (Tritium): —")
        self._squad_fuel_label.setStyleSheet(self._LABEL_STYLE)
        self._squad_docking_label = QLabel("Docking: —")
        self._squad_docking_label.setStyleSheet(self._LABEL_STYLE)
        squad_row1.addWidget(self._squad_location_label)
        squad_row1.addWidget(self._squad_fuel_label)
        squad_row1.addWidget(self._squad_docking_label)
        squad_row1.addStretch()
        squad_layout.addLayout(squad_row1)

        squad_row2 = QHBoxLayout()
        self._squad_jump_range_label = QLabel("Jump range: —")
        self._squad_jump_range_label.setStyleSheet(self._LABEL_STYLE)
        self._squad_space_label = QLabel("Free space: —")
        self._squad_space_label.setStyleSheet(self._LABEL_STYLE)
        squad_row2.addWidget(self._squad_jump_range_label)
        squad_row2.addWidget(self._squad_space_label)
        squad_row2.addStretch()
        squad_layout.addLayout(squad_row2)

        self._squad_finance_label = QLabel("—")
        self._squad_finance_label.setWordWrap(True)
        self._squad_finance_label.setStyleSheet(self._LABEL_STYLE)
        squad_layout.addWidget(self._squad_finance_label)

        root.addWidget(squad_frame)

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
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        h = self._orders_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._orders_table, 1)

    # Real max Fleet Carrier fuel capacity — carriers run purely on Tritium,
    # capped at 1000t, so a bare tonnage number doesn't convey how close to
    # empty (or how full) that actually is.
    _MAX_FUEL_T = 1000

    def _fuel_text_and_color(self, fuel) -> tuple[str, str]:
        if not isinstance(fuel, int):
            return "Fuel (Tritium): —", ""
        pct = fuel / self._MAX_FUEL_T * 100
        color = "#FF6B6B" if pct < 20 else ("#FFD93D" if pct < 50 else "#6BCB77")
        return f"Fuel (Tritium): {fuel:,} / {self._MAX_FUEL_T:,} t ({pct:.0f}%)", color

    def refresh(self, state) -> None:
        self._refresh_squadron_carrier(state)

        callsign = getattr(state, "carrier_callsign", None)
        if not callsign:
            self._name_label.setText("No fleet carrier detected.")
            self._location_label.setText("Location: —")
            self._fuel_label.setText("Fuel (Tritium): —")
            self._docking_label.setText("Docking: —")
            self._jump_range_label.setText("Jump range: —")
            self._space_label.setText("Free space: —")
            self._next_jump_label.setVisible(False)
            self._finance_label.setText("—")
            _empty(self._orders_table, "No fleet carrier detected.")
            return

        name = getattr(state, "carrier_name", None) or ""
        self._name_label.setText(f"{name} ({callsign})" if name else callsign)

        location = getattr(state, "carrier_current_system", None) or "—"
        self._location_label.setText(f"Location: {location}")

        fuel = getattr(state, "carrier_fuel_level", None)
        text, color = self._fuel_text_and_color(fuel)
        self._fuel_label.setText(text)
        self._fuel_label.setStyleSheet(self._LABEL_STYLE + f" color:{color};" if color else self._LABEL_STYLE)

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
        if not rows:
            _empty(self._orders_table, "No active buy/sell orders set on this carrier.")
            return
        _rows(self._orders_table, len(rows))
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

    def _refresh_squadron_carrier(self, state) -> None:
        sc = getattr(state, "squadron_carrier", None)
        if not isinstance(sc, dict) or not sc.get("callsign"):
            self._squad_name_label.setText("No squadron carrier data recorded yet.")
            self._squad_location_label.setText("Location: —")
            self._squad_fuel_label.setText("Fuel (Tritium): —")
            self._squad_docking_label.setText("Docking: —")
            self._squad_jump_range_label.setText("Jump range: —")
            self._squad_space_label.setText("Free space: —")
            self._squad_finance_label.setText("—")
            return

        name = sc.get("name") or ""
        callsign = sc["callsign"]
        self._squad_name_label.setText(f"{name} ({callsign})" if name else callsign)

        location = sc.get("current_system") or "—"
        self._squad_location_label.setText(f"Location: {location}")

        fuel = sc.get("fuel_level")
        text, color = self._fuel_text_and_color(fuel)
        self._squad_fuel_label.setText(text)
        self._squad_fuel_label.setStyleSheet(self._LABEL_STYLE + f" color:{color};" if color else self._LABEL_STYLE)

        docking = sc.get("docking_access") or "—"
        self._squad_docking_label.setText(f"Docking: {docking.title() if isinstance(docking, str) else docking}")

        curr = sc.get("jump_range_curr")
        maxr = sc.get("jump_range_max")
        if isinstance(curr, float) and isinstance(maxr, float):
            self._squad_jump_range_label.setText(f"Jump range: {curr:.1f} / {maxr:.1f} ly")
        else:
            self._squad_jump_range_label.setText("Jump range: —")

        space = sc.get("space_usage") or {}
        free = space.get("FreeSpace")
        total = space.get("TotalCapacity")
        if isinstance(free, int) and isinstance(total, int):
            self._squad_space_label.setText(f"Free space: {free:,} / {total:,} t")
        else:
            self._squad_space_label.setText("Free space: —")

        finance = sc.get("finance") or {}
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
            self._squad_finance_label.setText(" | ".join(parts) if parts else "—")
        else:
            self._squad_finance_label.setText("—")
