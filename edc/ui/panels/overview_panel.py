import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)


class OverviewPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Overview tab.
    Contains system card, factions table, and overview actions label.

    Emits navigate_to(int) when the user clicks a hyperlink in the
    overview actions label. main_window connects this signal to
    self.sidebar.setCurrentRow().
    """

    navigate_to = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.overview_actions = QLabel("")
        self.overview_actions.setWordWrap(True)
        self.overview_actions.setTextFormat(Qt.TextFormat.RichText)
        self.overview_actions.setOpenExternalLinks(False)
        self.overview_actions.linkActivated.connect(
            self._on_overview_action_link
        )

        self._overview_opacity = QGraphicsOpacityEffect(self.overview_actions)
        self.overview_actions.setGraphicsEffect(self._overview_opacity)
        self._overview_opacity.setOpacity(1.0)
        self._last_overview_html = ""
        self._last_overview_lines = set()
        self._overview_anim = None

        self.system_card = QTextEdit()
        self.system_card.setReadOnly(True)
        self.system_card.setMinimumHeight(180)

        self.factions_table = QTableWidget()
        self.factions_table.setColumnCount(6)
        self.factions_table.setHorizontalHeaderLabels(
            ["Faction", "Government", "Allegiance", "Active", "Influence", "Rep"]
        )
        self.factions_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.factions_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.factions_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.factions_table.verticalHeader().setVisible(False)
        self.factions_table.setShowGrid(False)
        self.factions_table.setAlternatingRowColors(True)
        self.factions_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.factions_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.factions_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.factions_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.factions_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.factions_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self.factions_table.setMinimumHeight(280)

        top_label = QLabel("System")
        top_label.setContentsMargins(0, 0, 0, 0)

        bottom_label = QLabel("Factions (top by influence)")
        bottom_label.setContentsMargins(0, 0, 0, 0)

        top_panel = QWidget()
        top_l = QVBoxLayout(top_panel)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.addWidget(top_label)
        top_l.addWidget(self.system_card)

        bottom_panel = QWidget()
        bot_l = QVBoxLayout(bottom_panel)
        bot_l.setContentsMargins(0, 0, 0, 0)
        bot_l.addWidget(bottom_label)
        bot_l.addWidget(self.factions_table)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top_panel)
        split.addWidget(bottom_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 7)
        split.setSizes([140, 520])

        layout.addWidget(self.overview_actions)
        layout.addWidget(split)

    def _on_overview_action_link(self, link: str):
        try:
            mapping = {
                "exploration": 1,
                "exobiology": 2,
                "powerplay": 3,
                "combat": 4,
                "intel": 5,
                "odyssey": 6,
                "materials": 7,
                "settings": 8,
                "log": 9,
            }
            idx = mapping.get(link)
            if idx is not None:
                self.navigate_to.emit(idx)
        except Exception:
            pass

    def animate_overview_update(self, html: str):
        try:
            if not isinstance(html, str):
                self.overview_actions.setText(html or "")
                return

            new_lines = set(html.split("<br>"))

            if not self._last_overview_html:
                self.overview_actions.setText(html)
                self._last_overview_html = html
                self._last_overview_lines = new_lines
                return

            if html == self._last_overview_html:
                return

            added_lines = new_lines - self._last_overview_lines

            self.overview_actions.setText(html)

            if added_lines:
                self._overview_opacity.setOpacity(0.0)

                anim = QPropertyAnimation(self._overview_opacity, b"opacity")
                anim.setDuration(220)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()

                self._overview_anim = anim

            self._last_overview_html = html
            self._last_overview_lines = new_lines

        except Exception:
            self.overview_actions.setText(html)

    def _norm_token(self, val):
        if not isinstance(val, str):
            return ""
        return val.replace("$", "").replace(";", "").replace("_", " ").strip().title()

    def refresh(self, state):
        if not state.system:
            self.system_card.setPlainText("No system data yet.")
            self.factions_table.setRowCount(0)
            return

        lines = []
        lines.append(f"System: {state.system}")
        if state.controlling_faction:
            lines.append(f"Controlling Faction: {state.controlling_faction}")

        meta = []
        allegiance = self._norm_token(
            getattr(state, "system_allegiance", None)
        )
        government = self._norm_token(
            getattr(state, "system_government", None)
        )
        security = self._norm_token(
            getattr(state, "system_security", None)
        )
        economy = self._norm_token(
            getattr(state, "system_economy", None)
        )
        population = fmt.int_commas(getattr(state, "population", None))

        if allegiance:
            meta.append(f"Allegiance: {allegiance}")
        if government:
            meta.append(f"Government: {government}")
        if security:
            meta.append(f"Security: {security}")
        if economy:
            meta.append(f"Economy: {economy}")
        if population:
            meta.append(f"Population: {population}")
        if meta:
            lines.append(" | ".join(meta))

        self.system_card.setPlainText("\n".join(lines))

        facs = []
        controlling_name = fmt.text(state.controlling_faction, default="")

        for f in (state.factions or []):
            if not isinstance(f, dict):
                continue

            name = fmt.text(f.get("Name"), default="Unknown")

            infl = f.get("Influence")
            infl_val = float(infl) if isinstance(infl, (float, int)) else -1.0
            infl_txt = (
                fmt.pct_1(infl_val, default="?") if infl_val >= 0 else "?"
            )

            government = fmt.text(
                f.get("Government_Localised")
                or self._norm_token(f.get("Government"))
                or f.get("Government")
                or "",
                default="",
            )

            allegiance = fmt.text(
                f.get("Allegiance_Localised")
                or self._norm_token(f.get("Allegiance"))
                or f.get("Allegiance")
                or "",
                default="",
            )

            active_txt = ""
            active_states = f.get("ActiveStates") or []
            if isinstance(active_states, list) and active_states:
                vals = []
                for st in active_states:
                    if not isinstance(st, dict):
                        continue
                    val = fmt.text(
                        st.get("State_Localised")
                        or self._norm_token(st.get("State"))
                        or st.get("State")
                        or "",
                        default="",
                    )
                    if val:
                        vals.append(val)
                active_txt = ", ".join(vals[:2])
            elif (
                f.get("FactionState")
                and str(f.get("FactionState")).strip().lower() != "none"
            ):
                active_txt = fmt.text(
                    self._norm_token(f.get("FactionState"))
                    or f.get("FactionState"),
                    default="",
                )

            rep = f.get("MyReputation")
            if isinstance(rep, (float, int)):
                rep_f = float(rep)
                if -1.0 <= rep_f <= 1.0:
                    rep_txt = f"{(rep_f * 100):.1f}%"
                else:
                    rep_txt = f"{rep_f:.1f}"
            else:
                rep_txt = ""

            is_controller = bool(
                controlling_name and name == controlling_name
            )
            display_name = f"{name} ★" if is_controller else name
            facs.append((
                infl_val, display_name, government, allegiance,
                active_txt, infl_txt, rep_txt, is_controller
            ))

        facs.sort(key=lambda x: x[0], reverse=True)
        top = facs[:12]
        self.factions_table.setRowCount(len(top))
        for r, (
            _infl_val, name, government, allegiance,
            active_txt, infl_txt, rep_txt, is_controller
        ) in enumerate(top):
            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(government),
                QTableWidgetItem(allegiance),
                QTableWidgetItem(active_txt),
                QTableWidgetItem(infl_txt),
                QTableWidgetItem(rep_txt),
            ]

            row_bg = None
            row_fg = None
            active_l = (active_txt or "").strip().lower()

            if is_controller:
                row_bg = QColor(35, 55, 85)
                row_fg = QColor(255, 255, 255)

            if active_l in {"war", "civil war"}:
                row_bg = QColor(95, 35, 35)
                row_fg = QColor(255, 235, 235)
            elif active_l == "election":
                row_bg = QColor(85, 70, 35)
                row_fg = QColor(255, 245, 220)

            try:
                rep_val = None
                txt = (rep_txt or "").replace("%", "").strip()
                if txt:
                    rep_val = float(txt)
                if rep_val is not None:
                    if rep_val >= 50:
                        items[5].setForeground(QColor(140, 255, 180))
                    elif rep_val < 0:
                        items[5].setForeground(QColor(255, 160, 160))
            except Exception:
                pass

            if active_l in {"war", "civil war"}:
                items[3].setBackground(QColor(140, 60, 60))
                items[3].setForeground(QColor(255, 255, 255))
            elif active_l == "election":
                items[3].setBackground(QColor(140, 110, 50))
                items[3].setForeground(QColor(255, 255, 255))

            if row_bg is not None:
                for it in items:
                    if it is not items[3]:
                        it.setBackground(row_bg)
                    if row_fg is not None and it is not items[5]:
                        it.setForeground(row_fg)

            for c, it in enumerate(items):
                self.factions_table.setItem(r, c, it)