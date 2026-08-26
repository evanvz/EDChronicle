"""Shared visual style constants for panel content — a dark 'card' aesthetic
used throughout the deep-dive panels (Engineering, Market, Trade Routes,
Fleet Carrier, Mining, PowerPlay Finder, Player Faction, Squadron).

Centralized here so every panel's cards/headers/labels/tables stay visually
identical instead of six near-duplicate copies of the same strings drifting
apart over time. Import CARD_STYLE / HDR_STYLE / etc. instead of redefining
them locally.

Buttons: three variants by intent, not just one flat orange rectangle —
PRIMARY_BUTTON_STYLE (affirmative actions: Add, Search, Save),
SECONDARY_BUTTON_STYLE (neutral actions inside a card, e.g. Refresh),
DANGER_BUTTON_STYLE (destructive actions: Remove, Delete, Clear).

Cards: CARD_VARIANTS below is the single palette every panel should draw
semantic (non-default) card colors from, instead of each panel hand-rolling
its own hex pair (which is how Combat/Intel/Exploration ended up with a
dozen near-duplicate one-off colors). "blue" is the neutral default used
for plain data/search-result cards; the others carry meaning and should
only be reached for when the card's content actually warrants it — a
rainbow of cards with no meaning behind the color is worse than the flat
look this replaces. Use CARD_STYLE/HDR_STYLE directly for the default, or
make_card(title, variant=...) for a semantic one.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

# ── Card container (the "box" a section of related widgets sits in) ───────
CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"

# ── Section header label sitting at the top of a card ──────────────────────
HDR_STYLE = (
    "color:#7a7a7a; font-size:12px; font-weight:bold; letter-spacing:1px;"
    " background:transparent; border:none;"
)

# ── Plain body label inside a card (form field captions, notes) ───────────
LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"

# ── Inline combo/spin boxes that sit inside a card ─────────────────────────
COMBO_STYLE = "background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"

# ── Table embedded in a card ───────────────────────────────────────────────
TABLE_STYLE = (
    "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
    " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
    "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
    " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
    "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
)

# ── Button variants ─────────────────────────────────────────────────────────
PRIMARY_BUTTON_STYLE = (
    "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
    " border-radius:3px; padding:3px 12px; font-weight:bold; }"
    "QPushButton:hover { background:#2a5a8a; }"
    "QPushButton:pressed { background:#15304a; }"
    "QPushButton:disabled { background:#101820; color:#4a4a4a; border-color:#1a2530; }"
)

SECONDARY_BUTTON_STYLE = (
    "QPushButton { background:#0f1c2a; color:#c8c8c8; border:1px solid #2a3a4a;"
    " border-radius:3px; padding:3px 12px; }"
    "QPushButton:hover { background:#182838; border-color:#3a5a7a; color:#FFB347; }"
    "QPushButton:pressed { background:#0a141f; }"
    "QPushButton:disabled { background:#0d1218; color:#3a3a3a; border-color:#1a2028; }"
)

DANGER_BUTTON_STYLE = (
    "QPushButton { background:#2a1010; color:#FF8080; border:1px solid #5a2a2a;"
    " border-radius:3px; padding:2px 10px; }"
    "QPushButton:hover { background:#3a1818; border-color:#7a3a3a; }"
    "QPushButton:pressed { background:#200c0c; }"
    "QPushButton:disabled { background:#151010; color:#4a3a3a; border-color:#251818; }"
)

# ── Empty-state placeholder text inside an otherwise-empty table/card ──────
EMPTY_STATE_STYLE = "color:#4a4a4a; font-style:italic; background:transparent; border:none;"

# ── Semantic card palette ───────────────────────────────────────────────────
# (card_bg, card_border, header_fg) per meaning. Pulled together from the
# colors already in use ad-hoc across combat_panel/intel_panel/exploration_
# panel/exobiology_panel/fleet_carrier_panel, so existing "personality"
# cards (Notoriety, Bounty Clearance, Exobiology, squadron carrier, ...)
# and any future card can draw from one consistent set instead of each
# panel inventing its own hex pair.
_VARIANT_COLORS = {
    # Neutral/default — plain data, search results, no status implied.
    "blue":   ("#0d1a2a", "#1e3a5a", "#7a7a7a"),
    # Positive / success / gaining ground.
    "green":  ("#0d1a12", "#2a5a3a", "#6BCB77"),
    # Caution / stale data / needs attention soon, not yet urgent.
    "yellow": ("#2a2200", "#4a4010", "#FFD93D"),
    # Danger / urgent / losing ground / destructive context.
    "red":    ("#2a0a0a", "#4a1e1e", "#FF8080"),
    # Secondary entity / not-exclusively-yours (e.g. squadron vs. own carrier).
    "purple": ("#1a0d1f", "#4a1e5a", "#b380d9"),
    # Resources / materials / mining.
    "teal":   ("#0d1a1a", "#1e3a3a", "#6BE6D9"),
}


def card_style(variant: str = "blue") -> str:
    """QFrame stylesheet for one semantic card variant. Falls back to the
    default blue for an unrecognised variant name rather than raising —
    a typo'd variant should degrade to "looks normal", not crash a panel."""
    bg, border, _ = _VARIANT_COLORS.get(variant, _VARIANT_COLORS["blue"])
    return f"QFrame {{ background:{bg}; border:1px solid {border}; border-radius:5px; }}"


def hdr_style(variant: str = "blue") -> str:
    """Header QLabel stylesheet matching card_style's variant."""
    _, _, fg = _VARIANT_COLORS.get(variant, _VARIANT_COLORS["blue"])
    return (
        f"color:{fg}; font-size:12px; font-weight:bold; letter-spacing:1px;"
        " background:transparent; border:none;"
    )


def make_card(title: str = "", variant: str = "blue") -> tuple[QFrame, QVBoxLayout]:
    """Build a standard card QFrame (with an optional bold header label
    already inserted) and return (frame, content_layout) so callers can
    keep adding widgets/layouts to content_layout. Saves every panel from
    re-typing the same four setup lines with a slightly different margin
    each time.

    variant picks a semantic color from CARD_VARIANTS (see module docstring)
    — leave it as "blue" for plain/neutral cards; only reach for a colored
    variant when the card's content actually carries that meaning."""
    frame = QFrame()
    frame.setStyleSheet(card_style(variant))
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 8)
    layout.setSpacing(6)
    if title:
        hdr = QLabel(title)
        hdr.setStyleSheet(hdr_style(variant))
        layout.addWidget(hdr)
    return frame, layout


def set_table_empty_message(table, message: str) -> None:
    """Put a single centered, italic placeholder row spanning every column
    into an otherwise-empty QTableWidget, instead of leaving a large blank
    card body with nothing to explain why. Call this INSTEAD of
    table.setRowCount(0) when there's genuinely nothing to show yet (no
    data fetched, nothing tracked, filters matched nothing) — call
    table.setRowCount(n) as normal once there's real data, which clears
    the placeholder along with everything else.

    Safe to call repeatedly (e.g. on every refresh() while still empty) —
    it always rebuilds the single placeholder row from scratch."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QTableWidgetItem

    table.setRowCount(1)
    cols = table.columnCount() or 1
    table.setSpan(0, 0, 1, cols)
    item = QTableWidgetItem(message)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    item.setForeground(QColor("#4a4a4a"))
    font = item.font()
    font.setItalic(True)
    item.setFont(font)
    table.setItem(0, 0, item)
