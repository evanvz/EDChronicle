import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

log = logging.getLogger(__name__)


class MaterialsPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Materials tab.
    Receives state and item_catalog via refresh().
    Knows nothing about main_window or repo.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: transparent;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a; border-radius: 5px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        outer.addWidget(card)

        hdr = QLabel("MATERIALS — COMMANDER INVENTORY")
        hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold;"
            "letter-spacing: 1px; padding: 4px 0px 2px 2px;"
            "background: transparent; border: none;"
        )
        layout.addWidget(hdr)

        self.inv_kind = QComboBox()
        self.inv_kind.addItems(["Raw", "Manufactured", "Encoded", "Odyssey"])
        self.inv_kind.currentTextChanged.connect(self._on_filter_changed)

        self.inv_filter = QLineEdit()
        self.inv_filter.setPlaceholderText(
            "Filter (e.g. selenium, polymer, wake...)"
        )
        self.inv_filter.textChanged.connect(self._on_filter_changed)

        self.inv_summary = QLabel("")
        self.inv_summary.setWordWrap(True)
        self.inv_summary.setStyleSheet(
            "color: #666666; font-size:12px; padding: 2px 0px;"
            "background: transparent; border: none;"
        )

        self.inv_table = QTableWidget()
        self.inv_table.setColumnCount(3)
        self.inv_table.setHorizontalHeaderLabels(
            ["Material", "Subtype", "Count"]
        )
        self.inv_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.inv_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.inv_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.inv_table.verticalHeader().setVisible(False)
        self.inv_table.setShowGrid(False)
        self.inv_table.setAlternatingRowColors(True)
        self.inv_table.setSortingEnabled(True)
        self.inv_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.inv_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.inv_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.inv_table.setMinimumHeight(120)

        lbl_cat = QLabel("Category:")
        lbl_cat.setStyleSheet("color: #888888; font-size:12px; background: transparent; border: none;")
        lbl_flt = QLabel("Filter:")
        lbl_flt.setStyleSheet("color: #888888; font-size:12px; background: transparent; border: none;")

        row_filter = QHBoxLayout()
        row_filter.addWidget(lbl_cat)
        row_filter.addWidget(self.inv_kind)
        row_filter.addWidget(lbl_flt)
        row_filter.addWidget(self.inv_filter, 1)

        layout.addLayout(row_filter)
        layout.addWidget(self.inv_summary)
        layout.addWidget(self.inv_table, 1)

        self._state = None
        self._item_catalog = None

    def _on_filter_changed(self):
        if self._state is not None:
            self.refresh(self._state, self._item_catalog)

    def refresh(self, state, item_catalog):
        self._state = state
        self._item_catalog = item_catalog
        try:
            kind = self.inv_kind.currentText()
            filt = (self.inv_filter.text() or "").strip().lower()

            src = {}
            if kind == "Raw":
                src = getattr(state, "materials_raw", {}) or {}
            elif kind == "Manufactured":
                src = getattr(state, "materials_manufactured", {}) or {}
            elif kind == "Encoded":
                src = getattr(state, "materials_encoded", {}) or {}
            elif kind == "Odyssey":
                sl = getattr(state, "shiplocker_items", {}) or {}
                bp = getattr(state, "backpack_items", {}) or {}
                src = {}
                for k, v in sl.items():
                    src[k] = src.get(k, 0) + v
                for k, v in bp.items():
                    src[k] = src.get(k, 0) + v

            if not isinstance(src, dict) or not src:
                if kind == "Odyssey":
                    self.inv_summary.setText(
                        "No ShipLocker inventory loaded yet.\n"
                        "Tip: open the on-foot inventory/locker screen "
                        "or relog so a 'ShipLocker' journal event is emitted."
                    )
                else:
                    self.inv_summary.setText(
                        "No materials inventory loaded yet.\n"
                        "Tip: open the in-game Inventory/Materials screen "
                        "or relog so a 'Materials' journal event is emitted."
                    )
                self.inv_table.setRowCount(0)
                return

            if kind == "Odyssey":
                localised = dict(getattr(state, "backpack_localised", {}) or {})
                localised.update(getattr(state, "shiplocker_localised", {}) or {})
            else:
                localised = getattr(state, "materials_localised", {}) or {}
            if not isinstance(localised, dict):
                localised = {}

            rows = []
            zero = 0
            low_threshold = 25
            low = 0

            for nm, cnt in src.items():
                if not isinstance(nm, str) or not isinstance(cnt, int):
                    continue
                key = nm.strip().lower()
                disp = localised.get(key) or key.replace("_", " ").title()
                if filt and (filt not in key and filt not in disp.lower()):
                    continue
                if cnt == 0:
                    zero += 1
                if cnt <= low_threshold:
                    low += 1
                subtype = ""
                try:
                    subtype = item_catalog.get_subtype_label(disp) or ""
                except Exception:
                    subtype = ""
                rows.append((cnt, disp, subtype, key))

            rows.sort(key=lambda x: (x[0], x[1].lower()))
            self.inv_table.setSortingEnabled(False)
            self.inv_table.setRowCount(len(rows))
            for r, (cnt, disp, subtype, _key) in enumerate(rows):
                self.inv_table.setItem(r, 0, QTableWidgetItem(disp))
                self.inv_table.setItem(r, 1, QTableWidgetItem(str(subtype or "")))
                self.inv_table.setItem(r, 2, QTableWidgetItem(str(cnt)))
            self.inv_table.setSortingEnabled(True)

            ts = (
                getattr(state, "shiplocker_last_update", None)
                if kind == "Odyssey"
                else getattr(state, "materials_last_update", None)
            )
            ts_txt = (
                f"Updated: {ts}"
                if isinstance(ts, str) and ts.strip()
                else "Updated: (unknown)"
            )
            cat_txt = ""
            try:
                if item_catalog.has_data():
                    lu = getattr(item_catalog, "last_updated", None)
                    lu_txt = (
                        f", updated {lu}"
                        if isinstance(lu, str) and lu.strip()
                        else ""
                    )
                    cat_txt = f" | Catalog: {item_catalog.count()}{lu_txt}"
            except Exception:
                cat_txt = ""
            summary = (
                f"{ts_txt} | Items: {len(src)} "
                f"| Low (≤{low_threshold}): {low} "
                f"| Zero: {zero}{cat_txt}"
            )
            self.inv_summary.setText(summary)
        except Exception:
            try:
                self.inv_summary.setText("")
                self.inv_table.setRowCount(0)
            except Exception:
                pass