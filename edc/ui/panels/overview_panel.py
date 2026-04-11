import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QScrollArea,
    QGraphicsOpacityEffect,
    QStyle,
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QSize, QRect, pyqtSignal
)
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)

# ── Faction data keys stored in UserRole ─────────────────────────────────────
_D_NAME        = "name"
_D_GOVERNMENT  = "government"
_D_ALLEGIANCE  = "allegiance"
_D_PENDING     = "pending"
_D_ACTIVE      = "active"
_D_INFL        = "infl"        # float 0-1
_D_INFL_TXT    = "infl_txt"
_D_REP         = "rep"         # float or None
_D_REP_TXT     = "rep_txt"
_D_IS_CTRL     = "is_ctrl"
_D_ROW_BG      = "row_bg"
_D_NAME_COLOR  = "name_color"
_D_BORDER      = "border_color"
_D_STATE_TAGS  = "state_tags"  # list of (text, bg, fg) tuples


# ── Badge rendering helper ────────────────────────────────────────────────────
def _state_badge_data(state_txt):
    """Return (text, bg_hex, fg_hex) for a faction state string."""
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


# ── Delegate ──────────────────────────────────────────────────────────────────
class FactionDelegate(QStyledItemDelegate):

    ROW_H       = 58
    PAD         = 10
    BAR_H       = 5
    BADGE_PAD_H = 6
    BADGE_PAD_V = 3
    BADGE_RADIUS = 4

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = option.rect
        pad = self.PAD

        # ── Row background ────────────────────────────────────────────────
        row_bg = QColor(data.get(_D_ROW_BG, "#161616"))
        painter.fillRect(r, row_bg)

        # ── Left border ───────────────────────────────────────────────────
        border_color = data.get(_D_BORDER, "transparent")
        if border_color and border_color != "transparent":
            painter.fillRect(
                QRect(r.left(), r.top(), 3, r.height()),
                QColor(border_color)
            )

        # ── Layout zones ──────────────────────────────────────────────────
        w = r.width()
        col_faction    = int(w * 0.28)
        col_govt       = int(w * 0.14)
        col_alleg      = int(w * 0.14)
        col_pending    = int(w * 0.16)
        col_active     = int(w * 0.16)
        col_infl       = w - col_faction - col_govt - col_alleg - col_pending - col_active - pad

        x_faction  = r.left() + pad + 3
        x_govt     = x_faction + col_faction
        x_alleg    = x_govt    + col_govt
        x_pending  = x_alleg   + col_alleg
        x_active   = x_pending + col_pending
        x_infl     = x_active  + col_active

        top = r.top()
        mid = top + self.ROW_H // 2

        # ── Name ──────────────────────────────────────────────────────────
        name_color = QColor(data.get(_D_NAME_COLOR, "#CCCCCC"))
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(9)
        painter.setFont(name_font)
        painter.setPen(QPen(name_color))
        name_rect = QRect(x_faction, top + 6, col_faction - pad, 20)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            data.get(_D_NAME, "")
        )

        # ── Rep ───────────────────────────────────────────────────────────
        rep = data.get(_D_REP)
        rep_txt = data.get(_D_REP_TXT, "")
        if rep_txt:
            if rep is not None and rep >= 50:
                rep_color = QColor("#6BCB77")
            elif rep is not None and rep < 0:
                rep_color = QColor("#FF6B6B")
            else:
                rep_color = QColor("#444444")
            rep_font = QFont()
            rep_font.setPointSize(8)
            painter.setFont(rep_font)
            painter.setPen(QPen(rep_color))
            rep_rect = QRect(x_faction, top + 22, col_faction - pad, 16)
            painter.drawText(
                rep_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                rep_txt
            )

        # ── Influence bar ─────────────────────────────────────────────────
        infl = data.get(_D_INFL, 0.0)
        bar_y = top + self.ROW_H - self.BAR_H - 4
        bar_w = col_faction - pad * 2
        # Background
        painter.fillRect(
            QRect(x_faction, bar_y, bar_w, self.BAR_H),
            QColor("#2a2a2a")
        )
        # Fill
        border_c = data.get(_D_BORDER, "#4D96FF")
        if border_c == "transparent":
            border_c = "#4D96FF"
        fill_w = max(2, int(bar_w * min(1.0, max(0.0, infl))))
        painter.fillRect(
            QRect(x_faction, bar_y, fill_w, self.BAR_H),
            QColor(border_c)
        )

        # ── Meta font ─────────────────────────────────────────────────────
        meta_font = QFont()
        meta_font.setPointSize(8)
        painter.setFont(meta_font)
        meta_color = QColor("#AAAAAA")
        painter.setPen(QPen(meta_color))

        # ── Government ────────────────────────────────────────────────────
        govt_rect = QRect(x_govt, top + 6, col_govt - pad, self.ROW_H - 16)
        painter.drawText(
            govt_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            data.get(_D_GOVERNMENT, "")
        )

        # ── Allegiance ────────────────────────────────────────────────────
        alleg_rect = QRect(x_alleg, top + 6, col_alleg - pad, self.ROW_H - 16)
        painter.drawText(
            alleg_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            data.get(_D_ALLEGIANCE, "")
        )

        # ── State badges helper ───────────────────────────────────────────
        def draw_badges(tags, x_start, col_w):
            bx = x_start
            by = top + 8
            badge_font = QFont()
            badge_font.setPointSize(8)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            fm = QFontMetrics(badge_font)
            for tag in tags:
                txt, bg_hex, fg_hex = tag
                tw = fm.horizontalAdvance(txt)
                bw = tw + self.BADGE_PAD_H * 2
                if bx + bw > x_start + col_w - pad:
                    bx = x_start
                    by += 16
                badge_rect = QRect(bx, by, bw, fm.height() + self.BADGE_PAD_V * 2)
                painter.setBrush(QColor(bg_hex))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(
                    badge_rect, self.BADGE_RADIUS, self.BADGE_RADIUS
                )
                painter.setPen(QPen(QColor(fg_hex)))
                painter.drawText(
                    badge_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    txt
                )
                bx += bw + 4

        # ── Pending badges ────────────────────────────────────────────────
        pending = data.get(_D_PENDING, [])
        if pending:
            draw_badges(pending, x_pending, col_pending)

        # ── Active badges ─────────────────────────────────────────────────
        active = data.get(_D_ACTIVE, [])
        if active:
            draw_badges(active, x_active, col_active)

        # ── Influence % ───────────────────────────────────────────────────
        infl_font = QFont()
        infl_font.setBold(True)
        infl_font.setPointSize(8)
        painter.setFont(infl_font)
        painter.setPen(QPen(name_color))
        infl_rect = QRect(x_infl, top + 6, col_infl - pad, 20)
        painter.drawText(
            infl_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            data.get(_D_INFL_TXT, "")
        )

        # ── Bottom separator ──────────────────────────────────────────────
        painter.setPen(QPen(QColor("#252525")))
        painter.drawLine(r.left(), r.top(), r.right(), r.top())
        painter.setPen(QPen(QColor("#111111")))
        painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

        painter.restore()


# ── Header widget ─────────────────────────────────────────────────────────────
class FactionHeader(QWidget):
    """Draws column headers that always match delegate column widths."""

    COLS = ["FACTION", "GOVERNMENT", "ALLEGIANCE", "PENDING", "ACTIVE", "INF"]
    WIDTHS = [0.28, 0.14, 0.14, 0.16, 0.16, 0.08]  # None = remainder

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        pad = 8

        used = sum(int(w * p) for p in self.WIDTHS if p is not None)
        col_ws = [int(w * p) if p else w - used for p in self.WIDTHS]

        x = pad + 3
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#555555")))

        for i, (label, cw) in enumerate(zip(self.COLS, col_ws)):
            align = (
                Qt.AlignmentFlag.AlignRight
                if i == len(self.COLS) - 1
                else Qt.AlignmentFlag.AlignLeft
            )
            painter.drawText(
                QRect(x, 0, cw - pad, 22),
                align | Qt.AlignmentFlag.AlignVCenter,
                label
            )
            x += cw

        # Bottom border
        painter.setPen(QPen(QColor("#2a2a2a")))
        painter.drawLine(0, 27, w, 21)
        painter.end()


# ── Panel ─────────────────────────────────────────────────────────────────────
class OverviewPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Overview tab.
    Factions displayed via QListWidget + FactionDelegate.

    Emits navigate_to(int) when a hyperlink in overview_actions is clicked.
    """

    navigate_to = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Actions label with fade animation ────────────────────────────
        self.overview_actions = QLabel("")
        self.overview_actions.setWordWrap(True)
        self.overview_actions.setTextFormat(Qt.TextFormat.RichText)
        self.overview_actions.setOpenExternalLinks(False)
        self.overview_actions.linkActivated.connect(
            self._on_overview_action_link
        )
        self.overview_actions.setContentsMargins(8, 8, 8, 4)

        self._overview_opacity = QGraphicsOpacityEffect(self.overview_actions)
        self.overview_actions.setGraphicsEffect(self._overview_opacity)
        self._overview_opacity.setOpacity(1.0)
        self._last_overview_html = ""
        self._last_overview_lines = set()
        self._overview_anim = None

        outer.addWidget(self.overview_actions)

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setSpacing(0)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        # ── System card ───────────────────────────────────────────────────
        self.system_display = QLabel("")
        self.system_display.setWordWrap(True)
        self.system_display.setTextFormat(Qt.TextFormat.RichText)
        self.system_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.system_display.setContentsMargins(0, 0, 0, 6)
        layout.addWidget(self.system_display)

        # ── Factions header ───────────────────────────────────────────────
        self.factions_header = FactionHeader()
        layout.addWidget(self.factions_header)

        # ── Factions list ─────────────────────────────────────────────────
        self.factions_list = QListWidget()
        self.factions_list.setItemDelegate(FactionDelegate())
        self.factions_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.factions_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.factions_list.setSelectionMode(
            QListWidget.SelectionMode.NoSelection
        )
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
                "exploration": 1, "exobiology": 2,
                "powerplay": 3,   "combat": 4,
                "intel": 5,       "odyssey": 6,
                "materials": 7,   "settings": 8,
                "log": 9,
            }
            idx = mapping.get(link)
            if idx is not None:
                self.navigate_to.emit(idx)
        except Exception:
            pass

    # ── Animated actions update ───────────────────────────────────────────────
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

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _norm_token(self, val):
        if not isinstance(val, str):
            return ""
        return (
            val.replace("$", "").replace(";", "")
            .replace("_", " ").strip().title()
        )

    def _esc(self, t):
        return str(t or "").replace(
            "&", "&amp;"
        ).replace("<", "&lt;").replace(">", "&gt;")

    # ── Main refresh ──────────────────────────────────────────────────────────
    def refresh(self, state):
        if not state.system:
            self.system_display.setText("")
            self.factions_list.clear()
            return
        self._refresh_system_card(state)
        self._refresh_factions(state)

    # ── System card ───────────────────────────────────────────────────────────
    def _refresh_system_card(self, state):
        esc = self._esc
        html = []

        html.append(
            f'<span style="font-size:15px;font-weight:700;'
            f'color:#4D96FF;">🌟 {esc(state.system)}</span>'
        )

        if state.controlling_faction:
            html.append(
                f'<br><span style="color:#FFD93D;font-weight:700;">'
                f'Controlling: {esc(state.controlling_faction)}</span>'
            )

        meta_parts = []
        for icon, attr in [
            ("⚑", "system_allegiance"),
            ("🏛", "system_government"),
            ("🛡", "system_security"),
            ("💰", "system_economy"),
        ]:
            val = self._norm_token(getattr(state, attr, None))
            if val:
                meta_parts.append(f'{icon} {esc(val)}')

        population = fmt.int_commas(getattr(state, "population", None))
        if population:
            meta_parts.append(f'👥 {esc(population)}')

        if meta_parts:
            html.append(
                f'<br><span style="color:#888888;font-size:11px;">'
                + ' &nbsp; '.join(meta_parts)
                + '</span>'
            )

        self.system_display.setText(
            "<html><body>" + "".join(html) + "</body></html>"
        )

    # ── Factions list ─────────────────────────────────────────────────────────
    def _refresh_factions(self, state):
        self.factions_list.clear()

        controlling_name = fmt.text(state.controlling_faction, default="")
        facs = []

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
                or self._norm_token(f.get("Government")) or "",
                default="",
            )
            allegiance = fmt.text(
                f.get("Allegiance_Localised")
                or self._norm_token(f.get("Allegiance")) or "",
                default="",
            )

            # Pending state badges
            pending_tags = []
            for ps in (f.get("PendingStates") or []):
                if not isinstance(ps, dict):
                    continue
                val = fmt.text(
                    ps.get("State_Localised")
                    or self._norm_token(ps.get("State")) or "",
                    default="",
                )
                tag = _state_badge_data(val)
                if tag:
                    pending_tags.append(tag)

            # Active state badges
            active_tags = []
            active_l = ""
            active_states = f.get("ActiveStates") or []
            if isinstance(active_states, list) and active_states:
                for st in active_states:
                    if not isinstance(st, dict):
                        continue
                    val = fmt.text(
                        st.get("State_Localised")
                        or self._norm_token(st.get("State")) or "",
                        default="",
                    )
                    tag = _state_badge_data(val)
                    if tag:
                        active_tags.append(tag)
                first = active_states[0]
                if isinstance(first, dict):
                    active_l = str(
                        first.get("State_Localised")
                        or first.get("State") or ""
                    ).strip().lower()
            elif (
                f.get("FactionState")
                and str(f.get("FactionState")).strip().lower() != "none"
            ):
                fs_txt = fmt.text(
                    self._norm_token(f.get("FactionState"))
                    or f.get("FactionState"),
                    default="",
                )
                tag = _state_badge_data(fs_txt)
                if tag:
                    active_tags.append(tag)
                active_l = str(f.get("FactionState")).strip().lower()

            rep = f.get("MyReputation")
            rep_val = None
            rep_txt = ""
            if isinstance(rep, (float, int)):
                rep_val = float(rep)
                rep_txt = f"{rep_val:.1f}%"

            is_ctrl = bool(controlling_name and name == controlling_name)

            # Row colours
            if active_l in {"war", "civil war"}:
                row_bg = "#2a0a0a"
                name_color = "#FFB0B0"
                border = "#FF4444"
            elif active_l == "election":
                row_bg = "#1e1800"
                name_color = "#FFE8A0"
                border = "#FFD93D"
            elif active_l in {"boom", "expansion"}:
                row_bg = "#0a1a0a"
                name_color = "#CCFFCC"
                border = "#6BCB77"
            elif is_ctrl:
                row_bg = "#0a1e2e"
                name_color = "#7EC8FF"
                border = "#4D96FF"
            else:
                row_bg = "#161616"
                name_color = "#CCCCCC"
                border = "transparent"

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
            }))

        facs.sort(key=lambda x: x[0], reverse=True)

        for _, data in facs[:12]:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setSizeHint(QSize(0, FactionDelegate.ROW_H))
            self.factions_list.addItem(item)

        # Resize list to fit all items without scrollbar
        total_h = self.factions_list.count() * FactionDelegate.ROW_H
        self.factions_list.setFixedHeight(total_h + 4)
