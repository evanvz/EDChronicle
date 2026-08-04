"""Shared semantic color palette and type scale for panel stylesheets.

Established after a design-consistency review: special-purpose cards had
accumulated 20+ near-duplicate one-off background colors (multiple slightly
different "dark red" cards, etc.), and the vast majority of visible data
text ran at 9-11px — 2-4px under the app's own global default (13px, set in
app.py). Panels should pull from this module by MEANING rather than picking
a new hex whenever a card needs to look "different enough."

Each accent is (text, background, border). The neutral card chrome
(CARD_BG/CARD_BORDER) was already consistent app-wide and is unchanged here.
"""

CARD_BG = "#0d1a2a"
CARD_BORDER = "#1e3a5a"

# ── Semantic accents — pick by meaning, not by what hasn't been used yet ──
DANGER   = ("#FF6B6B", "#2a0a0a", "#4a1e1e")   # urgent/threat: war, bounty, hostile
WARNING  = ("#d0a060", "#201a0d", "#4a3a1e")   # caution/attention: notoriety, defensive PP systems
POSITIVE = ("#6BCB77", "#0d1a0d", "#1e3a1e")   # stable/good: boom, controlling, all-clear
INFO     = ("#6be6d9", "#0d2a2a", "#1e4a45")   # informational/intel: codex, community/Spansh data
SHARED   = ("#C77DFF", "#1a0d1f", "#3a1a45")   # shared/squadron-scope data: squadron carrier
PENDING  = ("#FFD93D", "#201a0d", "#4a3a1e")   # in-progress/needs input: election, CSV import note

# ── Text ───────────────────────────────────────────────────────────────
# Live game data must always read as more prominent than static hint text —
# the two were previously often the same dim gray, making real values blend
# into permanent instructional copy.
TEXT_DATA = "#E6E6E6"      # live values from the game — matches the app's global default
TEXT_BODY = "#c8c8c8"      # normal body text
TEXT_HINT = "#8a8a8a"      # static/instructional text only — neutral card bg, never a colored one
TEXT_HEADER = "#6a7a8a"    # small-caps card section headers

# ── Type scale (px) ───────────────────────────────────────────────────
SIZE_DATA = 12      # primary values/data — matches the app's 13px default closely
SIZE_BODY = 12
SIZE_META = 11       # secondary meta text (previously often 9-10px)
SIZE_HEADER = 10      # small-caps card headers
