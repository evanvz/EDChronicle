import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QScrollArea,
    QGraphicsOpacityEffect,
    QFrame,
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QSize, QRect, pyqtSignal
)
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)

# ── Faction data keys ─────────────────────────────────────────────────────────
_D_NAME       = "name"
_D_GOVERNMENT = "government"
_D_ALLEGIANCE = "allegiance"
_D_PENDING    = "pending"
_D_ACTIVE     = "active"
_D_INFL       = "infl"
_D_INFL_TXT   = "infl_txt"
_D_REP        = "rep"
_D_REP_TXT    = "rep_txt"
_D_IS_CTRL    = "is_ctrl"
_D_ROW_BG     = "row_bg"
_D_NAME_COLOR = "name_color"
_D_BORDER     = "border_color"
_D_CONFLICT   = "conflict"


def _state_badge_data(state_txt):
    sl = str(state_txt or "").strip().lower()
    if not sl or sl == "none":
        return None
    if sl in {"war", "civil war"}:
        return (state_txt, "#5F2323", "#FF6B6B")
    if sl == "civil unrest":
        return (state_txt, "#3a2a00", "#FFB347")
    if sl == "election":
        return (state_txt, "#3a2e00", "#FFD93D")
    if sl == "boom":
        return (state_txt, "#1a3a1a", "#6BCB77")
    if sl == "expansion":
        return (state_txt, "#1a2a3a", "#4D96FF")
    if sl in {"bust", "famine", "outbreak", "infrastructure failure"}:
        return (state_txt, "#3a1a1a", "#FF8888")
    if sl in {"lockdown", "retreat"}:
        return (state_txt, "#2a1a2a", "#C77DFF")
    return (state_txt, "#2a2a2a", "#AAAAAA")


# ── Faction delegate ──────────────────────────────────────────────────────────
class FactionDelegate(QStyledItemDelegate):

    ROW_H        = 58
    PAD          = 10
    BAR_H        = 4
    BADGE_PAD_H  = 5
    BADGE_PAD_V  = 2
    BADGE_RADIUS = 3

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r   = option.rect
        pad = self.PAD
        w   = r.width()
        top = r.top()

        # Row bg + left border
        painter.fillRect(r, QColor(data.get(_D_ROW_BG, "#161616")))
        border_c = data.get(_D_BORDER, "transparent")
        if border_c and border_c != "transparent":
            painter.fillRect(
                QRect(r.left(), r.top(), 3, r.height()),
                QColor(border_c)
            )

        # Column layout
        col_faction = int(w * 0.30)
        col_govt    = int(w * 0.14)
        col_alleg   = int(w * 0.14)
        col_pending = int(w * 0.16)
        col_active  = int(w * 0.16)
        col_infl    = w - col_faction - col_govt - col_alleg - col_pending - col_active - pad

        x_fac  = r.left() + pad + 3
        x_gov  = x_fac  + col_faction
        x_ale  = x_gov  + col_govt
        x_pen  = x_ale  + col_alleg
        x_act  = x_pen  + col_pending
        x_inf  = x_act  + col_active

        name_color = QColor(data.get(_D_NAME_COLOR, "#CCCCCC"))

        # Name
        f = QFont(); f.setBold(True); f.setPointSize(9)
        painter.setFont(f); painter.setPen(QPen(name_color))
        painter.drawText(
            QRect(x_fac, top + 6, col_faction - pad, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            data.get(_D_NAME, "")
        )

        # Rep
        rep     = data.get(_D_REP)
        rep_txt = data.get(_D_REP_TXT, "")
        if rep_txt:
            rc = (
                QColor("#6BCB77") if rep is not None and rep >= 50
                else QColor("#FF6B6B") if rep is not None and rep < 0
                else QColor("#444444")
            )
            rf = QFont(); rf.setPointSize(7)
            painter.setFont(rf); painter.setPen(QPen(rc))
            painter.drawText(
                QRect(x_fac, top + 24, col_faction - pad, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Rep: {rep_txt}"
            )

        # Influence bar
        infl  = data.get(_D_INFL, 0.0)
        bar_y = top + self.ROW_H - self.BAR_H - 4
        bar_w = col_faction - pad * 2
        painter.fillRect(QRect(x_fac, bar_y, bar_w, self.BAR_H), QColor("#2a2a2a"))
        bc = border_c if border_c != "transparent" else "#4D96FF"
        fw = max(2, int(bar_w * min(1.0, max(0.0, infl))))
        painter.fillRect(QRect(x_fac, bar_y, fw, self.BAR_H), QColor(bc))

        # Government + Allegiance
        mf = QFont(); mf.setPointSize(8)
        painter.setFont(mf); painter.setPen(QPen(QColor("#AAAAAA")))
        painter.drawText(
            QRect(x_gov, top + 6, col_govt - pad, self.ROW_H - 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            data.get(_D_GOVERNMENT, "")
        )
        painter.drawText(
            QRect(x_ale, top + 6, col_alleg - pad, self.ROW_H - 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            data.get(_D_ALLEGIANCE, "")
        )

        # Badge helper
        def draw_badges(tags, x_start, col_w):
            bx = x_start
            by = top + 8
            bf = QFont(); bf.setPointSize(7); bf.setBold(True)
            painter.setFont(bf)
            fm = QFontMetrics(bf)
            for tag in tags:
                txt, bg_hex, fg_hex = tag
                bw = fm.horizontalAdvance(txt) + self.BADGE_PAD_H * 2
                if bx + bw > x_start + col_w - pad:
                    bx = x_start; by += 15
                br = QRect(bx, by, bw, fm.height() + self.BADGE_PAD_V * 2)
                painter.setBrush(QColor(bg_hex))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(br, self.BADGE_RADIUS, self.BADGE_RADIUS)
                painter.setPen(QPen(QColor(fg_hex)))
                painter.drawText(br, Qt.AlignmentFlag.AlignCenter, txt)
                bx += bw + 3

        draw_badges(data.get(_D_PENDING, []), x_pen, col_pending)
        draw_badges(data.get(_D_ACTIVE,  []), x_act, col_active)

        # Influence %
        inf = QFont(); inf.setBold(True); inf.setPointSize(9)
        painter.setFont(inf); painter.setPen(QPen(name_color))
        painter.drawText(
            QRect(x_inf, top + 6, col_infl - pad, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            data.get(_D_INFL_TXT, "")
        )

        # Separators
        painter.setPen(QPen(QColor("#252525")))
        painter.drawLine(r.left(), r.top(), r.right(), r.top())
        painter.setPen(QPen(QColor("#111111")))
        painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

        painter.restore()


# ── Faction header ────────────────────────────────────────────────────────────
class FactionHeader(QWidget):
    COLS   = ["FACTION", "GOVERNMENT", "ALLEGIANCE", "PENDING", "ACTIVE", "INF"]
    WIDTHS = [0.30, 0.14, 0.14, 0.16, 0.16, 0.08]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w   = self.width()
        pad = 10
        col_ws = [int(w * pw) for pw in self.WIDTHS]
        x = pad + 3
        f = QFont(); f.setPointSize(8); f.setBold(True)
        p.setFont(f); p.setPen(QPen(QColor("#667788")))
        for i, (label, cw) in enumerate(zip(self.COLS, col_ws)):
            align = (
                Qt.AlignmentFlag.AlignRight
                if i == len(self.COLS) - 1
                else Qt.AlignmentFlag.AlignLeft
            )
            p.drawText(QRect(x, 0, cw - pad, 22), align | Qt.AlignmentFlag.AlignVCenter, label)
            x += cw
        p.setPen(QPen(QColor("#2a2a2a")))
        p.drawLine(0, 21, w, 21)
        p.end()


# ── Main panel ────────────────────────────────────────────────────────────────
class OverviewPanel(QWidget):
    """
    Inara-inspired Overview tab.
    Sections: Actions | System card | Conflicts | Factions table
    Emits navigate_to(int) for tab navigation links.
    """

    navigate_to = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("background-color: #0d0d0d;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Actions strip ─────────────────────────────────────────────────
        self.overview_actions = QLabel("")
        self.overview_actions.setWordWrap(True)
        self.overview_actions.setTextFormat(Qt.TextFormat.RichText)
        self.overview_actions.setOpenExternalLinks(False)
        self.overview_actions.linkActivated.connect(self._on_overview_action_link)
        self.overview_actions.setContentsMargins(8, 6, 8, 6)
        self.overview_actions.setStyleSheet(
            "background-color: #0a0f1a; border-bottom: 1px solid #1a2a3a; color: #E6E6E6;"
        )

        self._overview_opacity = QGraphicsOpacityEffect(self.overview_actions)
        self.overview_actions.setGraphicsEffect(self._overview_opacity)
        self._overview_opacity.setOpacity(1.0)
        self._last_overview_html  = ""
        self._last_overview_lines = set()
        self._overview_anim       = None
        outer.addWidget(self.overview_actions)

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #0d0d0d; border: none; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background-color: #0d0d0d;")
        layout = QVBoxLayout(content)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        # ── System card ───────────────────────────────────────────────────
        self.system_card = QFrame()
        self.system_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.system_card.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 6px; }"
        )
        card_layout = QVBoxLayout(self.system_card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        # System name row
        self.lbl_system = QLabel("")
        self.lbl_system.setTextFormat(Qt.TextFormat.RichText)
        card_layout.addWidget(self.lbl_system)

        # Controlling faction
        self.lbl_controlling = QLabel("")
        self.lbl_controlling.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_controlling.setWordWrap(True)
        card_layout.addWidget(self.lbl_controlling)

        # Two column meta info
        meta_row = QHBoxLayout()
        meta_row.setSpacing(16)

        self.lbl_meta_left = QLabel("")
        self.lbl_meta_left.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_meta_left.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_meta_left.setWordWrap(True)

        self.lbl_meta_right = QLabel("")
        self.lbl_meta_right.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_meta_right.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_meta_right.setWordWrap(True)

        meta_row.addWidget(self.lbl_meta_left, 1)
        meta_row.addWidget(self.lbl_meta_right, 1)
        card_layout.addLayout(meta_row)

        layout.addWidget(self.system_card)

        # ── Conflicts section ─────────────────────────────────────────────
        self.conflict_widget = QWidget()
        self.conflict_widget.setStyleSheet("background: transparent;")
        self.conflict_layout = QVBoxLayout(self.conflict_widget)
        self.conflict_layout.setContentsMargins(0, 0, 0, 0)
        self.conflict_layout.setSpacing(4)
        self.conflict_widget.setVisible(False)
        layout.addWidget(self.conflict_widget)

        # ── Section label ─────────────────────────────────────────────────
        fac_label = QLabel("SYSTEM MINOR FACTIONS")
        fac_label.setStyleSheet(
            "color: #667788; font-size: 10px; font-weight: bold;"
            "letter-spacing: 1px; padding: 4px 0px 2px 2px;"
        )
        layout.addWidget(fac_label)

        # ── Faction header + list ─────────────────────────────────────────
        self.factions_header = FactionHeader()
        layout.addWidget(self.factions_header)

        self.factions_list = QListWidget()
        self.factions_list.setItemDelegate(FactionDelegate())
        self.factions_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.factions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.factions_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.factions_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.factions_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { border: none; }"
        )
        layout.addWidget(self.factions_list, 1)

    # ── Link handler ──────────────────────────────────────────────────────────
    def _on_overview_action_link(self, link: str):
        try:
            mapping = {
                "exploration": 1, "exobiology": 2, "powerplay": 3,
                "combat": 4, "intel": 5, "odyssey": 6,
                "materials": 7, "settings": 8, "log": 9,
            }
            idx = mapping.get(link)
            if idx is not None:
                self.navigate_to.emit(idx)
        except Exception:
            pass

    # ── Animated actions ──────────────────────────────────────────────────────
    def animate_overview_update(self, html: str):
        try:
            if not isinstance(html, str):
                self.overview_actions.setText(html or "")
                return
            new_lines = set(html.split("<br>"))
            if not self._last_overview_html:
                self.overview_actions.setText(html)
                self._last_overview_html  = html
                self._last_overview_lines = new_lines
                return
            if html == self._last_overview_html:
                return
            added = new_lines - self._last_overview_lines
            self.overview_actions.setText(html)
            if added:
                self._overview_opacity.setOpacity(0.0)
                anim = QPropertyAnimation(self._overview_opacity, b"opacity")
                anim.setDuration(220)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()
                self._overview_anim = anim
            self._last_overview_html  = html
            self._last_overview_lines = new_lines
        except Exception:
            self.overview_actions.setText(html)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _norm_token(self, val):
        if not isinstance(val, str):
            return ""
        return val.replace("$","").replace(";","").replace("_"," ").strip().title()

    def _esc(self, t):
        return str(t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    def _meta_row(self, label, value, label_color="#555555", value_color="#CCCCCC"):
        esc = self._esc
        return (
            f'<span style="color:{label_color};font-size:10px;">{esc(label)}</span>'
            f'&nbsp;<span style="color:{value_color};font-size:11px;">{esc(value)}</span><br>'
        )

    # ── Main refresh ──────────────────────────────────────────────────────────
    def refresh(self, state):
        if not state.system:
            self.lbl_system.setText("")
            self.lbl_controlling.setText("")
            self.lbl_meta_left.setText("")
            self.lbl_meta_right.setText("")
            self.conflict_widget.setVisible(False)
            self.factions_list.clear()
            return
        self._refresh_system_card(state)
        self._refresh_conflicts(state)
        self._refresh_factions(state)

    # ── System card ───────────────────────────────────────────────────────────
    def _refresh_system_card(self, state):
        esc = self._esc

        # System name
        self.lbl_system.setText(
            f'<span style="font-size:16px;font-weight:700;color:#4D96FF;">'
            f'🌟 {esc(state.system)}</span>'
        )

        # Controlling faction
        if state.controlling_faction:
            self.lbl_controlling.setText(
                f'<span style="color:#888888;font-size:10px;">CONTROLLING FACTION</span>'
                f'&nbsp;<span style="color:#FFB347;font-weight:700;font-size:12px;">'
                f'{esc(state.controlling_faction)}</span>'
            )
        else:
            self.lbl_controlling.setText("")

        # Left column — economy, government, allegiance
        left  = ""
        econ1 = self._norm_token(getattr(state, "system_economy", None))
        econ2 = self._norm_token(getattr(state, "system_economy_secondary", None))
        econ_display = econ1 or "—"
        if econ2 and econ2.lower() not in ("none", ""):
            econ_display += f" / {econ2}"
        left += self._meta_row("ECONOMY", econ_display)

        # Show controlling faction's active state
        ctrl_state = ""
        controlling = fmt.text(state.controlling_faction, default="")
        for f in (state.factions or []):
            if not isinstance(f, dict):
                continue
            if fmt.text(f.get("Name"), default="") == controlling:
                active = f.get("ActiveStates") or []
                if isinstance(active, list) and active:
                    first = active[0]
                    if isinstance(first, dict):
                        ctrl_state = fmt.text(
                            first.get("State_Localised")
                            or self._norm_token(first.get("State"))
                            or first.get("State") or "",
                            default=""
                        )
                elif f.get("FactionState") and str(
                    f.get("FactionState")
                ).strip().lower() != "none":
                    ctrl_state = self._norm_token(f.get("FactionState")) or ""
                break
        if ctrl_state:
            left += self._meta_row("STATE", ctrl_state, value_color="#FFD93D")
        left += self._meta_row(
            "GOVERNMENT",
            self._norm_token(getattr(state, "system_government", None)) or "—"
        )
        left += self._meta_row(
            "ALLEGIANCE",
            self._norm_token(getattr(state, "system_allegiance", None)) or "—"
        )
        pop = fmt.int_commas(getattr(state, "population", None))
        left += self._meta_row("POPULATION", pop or "—")
        self.lbl_meta_left.setText(f"<html><body>{left}</body></html>")

        # Right column — security, state
        right  = ""
        right += self._meta_row(
            "SECURITY",
            self._norm_token(getattr(state, "system_security", None)) or "—"
        )
        # PP state in system
        pp_state = getattr(state, "system_powerplay_state", None)
        pp_power = getattr(state, "system_controlling_power", None)
        if pp_power:
            pledged = getattr(state, "pp_power", None) or ""
            is_my_power = bool(
                pledged.strip().lower() == pp_power.strip().lower()
                if pledged else False
            )
            pp_display = f"★ {pp_power}" if is_my_power else pp_power
            pp_color   = "#FFB347" if is_my_power else "#CCCCCC"
            right += self._meta_row("POWERPLAY", pp_display, value_color=pp_color)
        if pp_state:
            right += self._meta_row("PP STATE", pp_state)
        self.lbl_meta_right.setText(f"<html><body>{right}</body></html>")

    # ── Conflicts section ─────────────────────────────────────────────────────
    def _refresh_conflicts(self, state):
        conflicts = getattr(state, "system_conflicts", None) or []

        # Clear existing conflict widgets
        while self.conflict_layout.count():
            item = self.conflict_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not conflicts:
            self.conflict_widget.setVisible(False)
            return

        self.conflict_widget.setVisible(True)

        # Section header
        hdr = QLabel("CONFLICTS")
        hdr.setStyleSheet(
            "color: #667788; font-size: 10px; font-weight: bold;"
            "letter-spacing: 1px; padding: 4px 0px 2px 2px;"
        )
        self.conflict_layout.addWidget(hdr)

        for c in conflicts:
            if not isinstance(c, dict):
                continue

            war_type = str(c.get("WarType", "")).lower()
            status   = str(c.get("Status",  "")).lower()
            f1       = c.get("Faction1") or {}
            f2       = c.get("Faction2") or {}
            f1_name  = str(f1.get("Name",    "") or "")
            f2_name  = str(f2.get("Name",    "") or "")
            f1_stake = str(f1.get("Stake")   or "")
            f2_stake = str(f2.get("Stake")   or "")
            f1_won   = int(f1.get("WonDays", 0) or 0)
            f2_won   = int(f2.get("WonDays", 0) or 0)

            if war_type == "election":
                label     = "ELECTION"
                tip       = "Complete non-combat missions, trade, exploration data"
                hdr_color = "#FFD93D"
                bg_color  = "#1e1800"
                bdr_color = "#FFD93D"
            elif war_type == "civilwar":
                label     = "CIVIL WAR"
                tip       = "Fight in Conflict Zones, hand in combat bonds"
                hdr_color = "#FF6B6B"
                bg_color  = "#2a0a0a"
                bdr_color = "#FF4444"
            else:
                label     = "WAR"
                tip       = "Fight in Conflict Zones, hand in combat bonds"
                hdr_color = "#FF6B6B"
                bg_color  = "#2a0a0a"
                bdr_color = "#FF4444"

            status_txt = "ACTIVE" if status == "active" else "PENDING"

            # Conflict card
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {bg_color}; border: 1px solid {bdr_color};"
                f"border-radius: 5px; }}"
            )
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(10, 6, 10, 6)
            card_l.setSpacing(4)

            # Header row — type + status
            top_row = QHBoxLayout()
            type_lbl = QLabel(
                f'<span style="color:{hdr_color};font-weight:700;font-size:11px;">'
                f'⚔ {label}</span>'
                f'&nbsp;<span style="color:#888888;font-size:10px;">({status_txt})</span>'
            )
            type_lbl.setTextFormat(Qt.TextFormat.RichText)
            top_row.addWidget(type_lbl)
            top_row.addStretch()
            card_l.addLayout(top_row)

            # Score row — faction1 | score | faction2
            score_row = QHBoxLayout()
            score_row.setSpacing(8)

            f1_lbl = QLabel(
                f'<span style="color:{hdr_color};font-weight:700;">'
                f'{self._esc(f1_name)}</span>'
                + (f'<br><span style="color:#888888;font-size:10px;">'
                   f'Asset: {self._esc(f1_stake)}</span>' if f1_stake else "")
            )
            f1_lbl.setTextFormat(Qt.TextFormat.RichText)
            f1_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)

            score_lbl = QLabel(
                f'<span style="color:#FFFFFF;font-weight:700;font-size:16px;">'
                f'{f1_won} vs {f2_won}</span>'
            )
            score_lbl.setTextFormat(Qt.TextFormat.RichText)
            score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            f2_lbl = QLabel(
                f'<span style="color:{hdr_color};font-weight:700;">'
                f'{self._esc(f2_name)}</span>'
                + (f'<br><span style="color:#888888;font-size:10px;">'
                   f'Asset: {self._esc(f2_stake)}</span>' if f2_stake else "")
            )
            f2_lbl.setTextFormat(Qt.TextFormat.RichText)
            f2_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

            score_row.addWidget(f1_lbl, 2)
            score_row.addWidget(score_lbl, 1)
            score_row.addWidget(f2_lbl, 2)
            card_l.addLayout(score_row)

            # Conflict type hint (brief)
            if war_type == "election":
                hint = "Non-combat only — trade, exploration, passengers"
            else:
                hint = "Fight in CZs · Hand in bonds at faction station"
            tip_lbl = QLabel(
                f'<span style="color:#666666;font-size:9px;">→ {self._esc(hint)}</span>'
            )
            tip_lbl.setTextFormat(Qt.TextFormat.RichText)
            card_l.addWidget(tip_lbl)

            self.conflict_layout.addWidget(card)

    # ── Factions ──────────────────────────────────────────────────────────────
    def _refresh_factions(self, state):
        self.factions_list.clear()
        controlling_name = fmt.text(state.controlling_faction, default="")

        # Conflict lookup
        conflict_map = {}
        for c in (getattr(state, "system_conflicts", None) or []):
            if not isinstance(c, dict):
                continue
            war_type = str(c.get("WarType", "")).lower()
            status   = str(c.get("Status",  "")).lower()
            f1       = c.get("Faction1") or {}
            f2       = c.get("Faction2") or {}
            f1_name  = str(f1.get("Name", ""))
            f2_name  = str(f2.get("Name", ""))
            f1_won   = int(f1.get("WonDays", 0) or 0)
            f2_won   = int(f2.get("WonDays", 0) or 0)
            stake    = str(f1.get("Stake") or f2.get("Stake") or "")

            type_label   = (
                "Election" if war_type == "election"
                else "Civil War" if war_type == "civilwar"
                else "War"
            )
            status_label = "Active" if status == "active" else "Pending"

            for fname, opponent, my_won, opp_won in [
                (f1_name, f2_name, f1_won, f2_won),
                (f2_name, f1_name, f2_won, f1_won),
            ]:
                if fname:
                    conflict_map[fname] = {
                        "type": type_label, "status": status_label,
                        "opponent": opponent, "my_won": my_won,
                        "opp_won": opp_won, "stake": stake,
                    }

        facs = []
        for f in (state.factions or []):
            if not isinstance(f, dict):
                continue

            name     = fmt.text(f.get("Name"), default="Unknown")
            infl     = f.get("Influence")
            infl_val = float(infl) if isinstance(infl, (float, int)) else -1.0
            infl_txt = fmt.pct_1(infl_val, default="?") if infl_val >= 0 else "?"

            government = fmt.text(
                f.get("Government_Localised")
                or self._norm_token(f.get("Government")) or "", default=""
            )
            allegiance = fmt.text(
                f.get("Allegiance_Localised")
                or self._norm_token(f.get("Allegiance")) or "", default=""
            )

            pending_tags = []
            for ps in (f.get("PendingStates") or []):
                if not isinstance(ps, dict):
                    continue
                val = fmt.text(
                    ps.get("State_Localised")
                    or self._norm_token(ps.get("State")) or "", default=""
                )
                tag = _state_badge_data(val)
                if tag:
                    pending_tags.append(tag)

            active_tags = []
            active_l    = ""
            active_states = f.get("ActiveStates") or []
            if isinstance(active_states, list) and active_states:
                for st in active_states:
                    if not isinstance(st, dict):
                        continue
                    val = fmt.text(
                        st.get("State_Localised")
                        or self._norm_token(st.get("State")) or "", default=""
                    )
                    tag = _state_badge_data(val)
                    if tag:
                        active_tags.append(tag)
                first = active_states[0]
                if isinstance(first, dict):
                    active_l = str(
                        first.get("State_Localised") or first.get("State") or ""
                    ).strip().lower()
            elif (
                f.get("FactionState")
                and str(f.get("FactionState")).strip().lower() != "none"
            ):
                fs = fmt.text(
                    self._norm_token(f.get("FactionState")) or f.get("FactionState"),
                    default=""
                )
                tag = _state_badge_data(fs)
                if tag:
                    active_tags.append(tag)
                active_l = str(f.get("FactionState")).strip().lower()

            rep     = f.get("MyReputation")
            rep_val = None
            rep_txt = ""
            if isinstance(rep, (float, int)):
                rep_val = float(rep)
                rep_txt = f"{rep_val:.1f}%"

            is_ctrl = bool(controlling_name and name == controlling_name)

            # Row colours — rep-based name colour like Inara (orange=allied)
            if active_l in {"war", "civil war"}:
                row_bg = "#2a0a0a"; name_color = "#FFB0B0"; border = "#FF4444"
            elif active_l == "election":
                row_bg = "#1e1800"; name_color = "#FFE8A0"; border = "#FFD93D"
            elif active_l in {"boom", "expansion"}:
                row_bg = "#0a1a0a"; name_color = "#CCFFCC"; border = "#6BCB77"
            elif is_ctrl:
                row_bg = "#0a1e2e"; name_color = "#7EC8FF"; border = "#4D96FF"
            else:
                row_bg = "#161616"; border = "transparent"
                # Inara-style: colour by rep level
                if rep_val is not None and rep_val >= 75:
                    name_color = "#FFB347"   # allied — orange
                elif rep_val is not None and rep_val >= 50:
                    name_color = "#FFD93D"   # friendly — yellow
                elif rep_val is not None and rep_val < 0:
                    name_color = "#FF6B6B"   # hostile — red
                else:
                    name_color = "#CCCCCC"   # neutral

            display_name = f"{name} ★" if is_ctrl else name

            facs.append((infl_val, {
                _D_NAME:       display_name,
                _D_GOVERNMENT: government,
                _D_ALLEGIANCE: allegiance,
                _D_PENDING:    pending_tags,
                _D_ACTIVE:     active_tags,
                _D_INFL:       infl_val,
                _D_INFL_TXT:   infl_txt,
                _D_REP:        rep_val,
                _D_REP_TXT:    rep_txt,
                _D_IS_CTRL:    is_ctrl,
                _D_ROW_BG:     row_bg,
                _D_NAME_COLOR: name_color,
                _D_BORDER:     border,
                _D_CONFLICT:   conflict_map.get(name),
            }))

        facs.sort(key=lambda x: x[0], reverse=True)

        for _, data in facs[:12]:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setSizeHint(QSize(0, FactionDelegate.ROW_H))
            self.factions_list.addItem(item)

        total_h = self.factions_list.count() * FactionDelegate.ROW_H
        self.factions_list.setFixedHeight(total_h + 4)
