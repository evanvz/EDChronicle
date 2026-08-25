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
"""
from __future__ import annotations

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


def make_card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Build a standard card QFrame (with an optional bold header label
    already inserted) and return (frame, content_layout) so callers can
    keep adding widgets/layouts to content_layout. Saves every panel from
    re-typing the same four setup lines with a slightly different margin
    each time."""
    frame = QFrame()
    frame.setStyleSheet(CARD_STYLE)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 8)
    layout.setSpacing(6)
    if title:
        hdr = QLabel(title)
        hdr.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr)
    return frame, layout
