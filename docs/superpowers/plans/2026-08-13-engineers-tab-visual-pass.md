# Engineers Tab Visual Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Engineers Reference Tab (`_EngineersTab` in `edc/ui/panels/engineering_panel.py`) so status is visible at a glance (color-coded card accents + a checkmark for Unlocked) and the tab uses its available horizontal space (3-column card grid instead of one full-width card per row).

**Architecture:** Pure internals change to one existing class. Replace each of the three sections' single "one QLabel rendering a concatenated HTML blob" with a `QGridLayout` (3 columns) holding one small rich-text `QLabel` per engineer card. No new files, no new state, no new journal handling — `refresh(state)` and `showEvent` keep their existing signatures and call sites.

**Tech Stack:** Python, PyQt6.

## Global Constraints

- Color table (exact values, from the approved design spec):
  - Unlocked: accent/status text `#6BCB77` (green), `✓ ` prefix on the status line, name text `#CCCCCC` (unchanged from today).
  - In Progress: accent/status text `#FFB347` (amber — this is the color already used for all status text today), name text `#CCCCCC`.
  - Not Encountered: accent `#555555`, status text `#888888` (unchanged from today), name text dimmed to `#999999` (down from `#CCCCCC`) — this stands in for the design spec's "~75% opacity", since Qt's rich-text (`QTextDocument`) CSS subset does not reliably support the CSS `opacity` property on block elements; dimming the name color achieves the same "this one fades into the background" effect through a property Qt definitely supports.
  - The "accent" is applied as the card's left border only, via CSS border shorthand's 4-value form (`border-width: 1px 1px 1px 3px`, `border-color: #1e3a5a #1e3a5a #1e3a5a <accent>`) — top/right/bottom stay the existing `#1e3a5a`, only the left edge widens to 3px and takes the status color.
- Layout: 3 columns per section, wrapping row by row (`row, col = divmod(i, 3)` over each section's sorted engineer list — matches today's existing `sorted(grouped[key])` ordering, unchanged).
- No new files. No new automated tests (grouping/sorting logic is unchanged — only rendering changes). Verify visually as the final step, per this project's convention that UI changes need live/visual confirmation before being called done.
- `_status_for()` (the unlocked/in_progress/not_encountered + status-text derivation) is unchanged — this plan only touches how a status is *rendered*, not how it's *computed*.
- `showEvent` (added in an earlier fix this session) is unchanged and must keep working: it calls `self.refresh(self._state)` when the tab becomes visible, and `refresh()` must still early-return when `not self.isVisible()`.

---

## File Structure

- **Modify:** `edc/ui/panels/engineering_panel.py` — `_EngineersTab.__init__`, `_EngineersTab._engineer_html`, `_EngineersTab.refresh`, plus a new `_EngineersTab._clear_grid` helper and a new module-level `_STATUS_ACCENT` table. Also add `QGridLayout` to the existing `PyQt6.QtWidgets` import line.

---

### Task 1: Color-coded 3-column grid for the Engineers tab

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`

**Interfaces:**
- Consumes: nothing new — same `EngineeringBlueprintTable` (`all_engineer_names()`, `all_engineer_requirements()`, `all_engineer_homes()`) and `state.engineer_progress` this class already reads.
- Produces: nothing new consumed elsewhere — `EngineeringPanel.refresh(state)` still calls `self._engineers_tab.refresh(state)` unchanged, and `showEvent` still calls `self.refresh(self._state)` unchanged. No other file in the codebase references `_EngineersTab` internals (`_sections`, `_engineer_html`) directly — confirmed via grep before writing this plan.

- [ ] **Step 1: Add the `QGridLayout` import**

Re-read the current import block at the top of `edc/ui/panels/engineering_panel.py` fresh before editing — this project's CLAUDE.md flags files in this directory as frequently-stale. As of this plan's writing, the block is:

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QTabWidget, QScrollArea,
)
```

Change it to add `QGridLayout`:

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QTabWidget, QScrollArea,
)
```

- [ ] **Step 2: Add the `_STATUS_ACCENT` table**

Add this module-level constant directly above the `class _EngineersTab(QWidget):` line (currently preceded by the end of `_OdysseyEngineeringTab`'s class body — place it as its own top-level block right before `_EngineersTab`, matching the file's existing convention of module-level style constants like `_HDR_STYLE`):

```python
_STATUS_ACCENT = {
    "unlocked": {"accent": "#6BCB77", "status_color": "#6BCB77", "name_color": "#CCCCCC", "check": "✓ "},
    "in_progress": {"accent": "#FFB347", "status_color": "#FFB347", "name_color": "#CCCCCC", "check": ""},
    "not_encountered": {"accent": "#555555", "status_color": "#888888", "name_color": "#999999", "check": ""},
}
```

- [ ] **Step 3: Replace the per-section `QLabel` with a `QGridLayout`, in `__init__`**

Current code (re-verify this is still the exact current text before editing — it was re-read fresh immediately before this plan was written):

```python
        self._sections: Dict[str, QLabel] = {}
        for key, label_text in (
            ("unlocked", "UNLOCKED"),
            ("in_progress", "IN PROGRESS"),
            ("not_encountered", "NOT ENCOUNTERED"),
        ):
            hdr = QLabel(label_text)
            hdr.setStyleSheet(_HDR_STYLE)
            content_layout.addWidget(hdr)
            body = QLabel("")
            body.setWordWrap(True)
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setStyleSheet("background: transparent; border: none;")
            content_layout.addWidget(body)
            self._sections[key] = body
```

Replace with:

```python
        self._section_grids: Dict[str, QGridLayout] = {}
        for key, label_text in (
            ("unlocked", "UNLOCKED"),
            ("in_progress", "IN PROGRESS"),
            ("not_encountered", "NOT ENCOUNTERED"),
        ):
            hdr = QLabel(label_text)
            hdr.setStyleSheet(_HDR_STYLE)
            content_layout.addWidget(hdr)

            grid_container = QWidget()
            grid_container.setStyleSheet("background: transparent;")
            grid = QGridLayout(grid_container)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            content_layout.addWidget(grid_container)
            self._section_grids[key] = grid
```

- [ ] **Step 4: Add the `_clear_grid` helper**

Add this method to `_EngineersTab`, directly after `_status_for` (before `_engineer_html`):

```python
    def _clear_grid(self, grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
```

- [ ] **Step 5: Rewrite `_engineer_html` to take a status group and apply its accent**

Current code:

```python
    def _engineer_html(self, name: str, status_text: str, req: Dict[str, str], home: Optional[Dict[str, Any]]) -> str:
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        dist_text = ""
        if home and all(isinstance(v, (int, float)) for v in (ref_x, ref_y, ref_z)):
            dist = ((home["x"] - ref_x) ** 2 + (home["y"] - ref_y) ** 2 + (home["z"] - ref_z) ** 2) ** 0.5
            dist_text = f" — {dist:.1f} ly"
        system_text = home.get("system_name") if home else None

        line = (
            '<div style="margin-bottom:10px;padding:4px 8px;'
            'background:#0d1a2a;border:1px solid #1e3a5a;border-radius:4px;">'
            f'<span style="color:#CCCCCC;font-weight:700;">{self._esc(name)}</span>'
        )
        if system_text:
            line += f' <span style="color:#4D96FF;font-size:12px;">— {self._esc(system_text)}{dist_text}</span>'
        line += f'<br><span style="color:#FFB347;font-size:12px;">{self._esc(status_text)}</span>'

        for field_key, field_label in (
            ("discover", "Discover"),
            ("meet", "Meet"),
            ("unlock", "Unlock"),
            ("referral", "Referral"),
        ):
            text = req.get(field_key)
            if text:
                line += (
                    f'<br><span style="color:#888888;font-size:12px;">'
                    f'&nbsp;&nbsp;{field_label}: {self._esc(text)}</span>'
                )

        line += '</div>'
        return line
```

Replace with (new `group: str` parameter, added right after `name`; `margin-bottom` dropped since `QGridLayout` spacing replaces it; border becomes the 4-value accent form; name/status colors come from `_STATUS_ACCENT`):

```python
    def _engineer_html(self, name: str, group: str, status_text: str, req: Dict[str, str], home: Optional[Dict[str, Any]]) -> str:
        accent = _STATUS_ACCENT[group]
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        dist_text = ""
        if home and all(isinstance(v, (int, float)) for v in (ref_x, ref_y, ref_z)):
            dist = ((home["x"] - ref_x) ** 2 + (home["y"] - ref_y) ** 2 + (home["z"] - ref_z) ** 2) ** 0.5
            dist_text = f" — {dist:.1f} ly"
        system_text = home.get("system_name") if home else None

        line = (
            '<div style="padding:4px 8px;background:#0d1a2a;'
            'border-width:1px 1px 1px 3px;border-style:solid;'
            f'border-color:#1e3a5a #1e3a5a #1e3a5a {accent["accent"]};border-radius:4px;">'
            f'<span style="color:{accent["name_color"]};font-weight:700;">{self._esc(name)}</span>'
        )
        if system_text:
            line += f' <span style="color:#4D96FF;font-size:12px;">— {self._esc(system_text)}{dist_text}</span>'
        line += (
            f'<br><span style="color:{accent["status_color"]};font-size:12px;">'
            f'{accent["check"]}{self._esc(status_text)}</span>'
        )

        for field_key, field_label in (
            ("discover", "Discover"),
            ("meet", "Meet"),
            ("unlock", "Unlock"),
            ("referral", "Referral"),
        ):
            text = req.get(field_key)
            if text:
                line += (
                    f'<br><span style="color:#888888;font-size:12px;">'
                    f'&nbsp;&nbsp;{field_label}: {self._esc(text)}</span>'
                )

        line += '</div>'
        return line
```

- [ ] **Step 6: Rewrite `refresh` to populate the grids instead of the section `QLabel`s**

Current code:

```python
    def refresh(self, state) -> None:
        self._state = state
        if not self.isVisible():
            # Tab isn't the one currently on screen -- no point paying for
            # 38 engineers' worth of HTML/section rebuilds the user can't
            # see. self._state is already cached above for when the tab
            # does become visible (see showEvent).
            return

        names = self._blueprints.all_engineer_names()
        requirements = self._blueprints.all_engineer_requirements()
        homes = self._blueprints.all_engineer_homes()

        grouped: Dict[str, List[str]] = {"unlocked": [], "in_progress": [], "not_encountered": []}
        statuses: Dict[str, str] = {}
        for name in names:
            group, status_text = self._status_for(name)
            grouped[group].append(name)
            statuses[name] = status_text

        for key in ("unlocked", "in_progress", "not_encountered"):
            entries = sorted(grouped[key])
            html = "".join(
                self._engineer_html(name, statuses[name], requirements.get(name) or {}, homes.get(name))
                for name in entries
            )
            self._sections[key].setText(
                html if html else
                '<span style="color:#444444;font-size:12px;">None.</span>'
            )
```

Replace with:

```python
    def refresh(self, state) -> None:
        self._state = state
        if not self.isVisible():
            # Tab isn't the one currently on screen -- no point paying for
            # 38 engineers' worth of card rebuilds the user can't see.
            # self._state is already cached above for when the tab does
            # become visible (see showEvent).
            return

        names = self._blueprints.all_engineer_names()
        requirements = self._blueprints.all_engineer_requirements()
        homes = self._blueprints.all_engineer_homes()

        grouped: Dict[str, List[str]] = {"unlocked": [], "in_progress": [], "not_encountered": []}
        statuses: Dict[str, str] = {}
        for name in names:
            group, status_text = self._status_for(name)
            grouped[group].append(name)
            statuses[name] = status_text

        for key in ("unlocked", "in_progress", "not_encountered"):
            grid = self._section_grids[key]
            self._clear_grid(grid)
            entries = sorted(grouped[key])
            if not entries:
                empty = QLabel('<span style="color:#444444;font-size:12px;">None.</span>')
                empty.setTextFormat(Qt.TextFormat.RichText)
                empty.setStyleSheet("background: transparent; border: none;")
                grid.addWidget(empty, 0, 0)
                continue
            for i, name in enumerate(entries):
                card = QLabel(
                    self._engineer_html(name, key, statuses[name], requirements.get(name) or {}, homes.get(name))
                )
                card.setWordWrap(True)
                card.setTextFormat(Qt.TextFormat.RichText)
                card.setStyleSheet("background: transparent; border: none;")
                row, col = divmod(i, 3)
                grid.addWidget(card, row, col)
```

- [ ] **Step 7: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest -q`
Expected: all 112 tests still pass (this task adds no new tests — no business logic changed, only rendering).

- [ ] **Step 9: Headless visual verification**

There's no automated test for rendering, so verify the real widget actually builds a 3-column grid with the right colors, the way the service-health status bar was verified earlier this session. Write a scratch script (in this project's scratchpad, not committed) that:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from edc.ui.panels.engineering_panel import _EngineersTab
from edc.core.engineering_blueprints import EngineeringBlueprintTable

app = QApplication([])
bp_table = EngineeringBlueprintTable(Path("settings"))
tab = _EngineersTab(bp_table)
tab.resize(900, 700)

class FakeState:
    engineer_progress = {
        # pick two real engineer names from settings/engineer_requirements.json
        # -- one Unlocked (rank >= 1), one In Progress (has "progress" text,
        # no rank) -- to exercise all three groups (the rest fall through to
        # not_encountered with no entry in engineer_progress at all).
    }
    system_x = system_y = system_z = None

tab.refresh(FakeState())  # while hidden -- grids stay empty, matches real startup
tab.show()
app.processEvents()  # showEvent fires -> refresh() runs again while visible

grid = tab._section_grids["not_encountered"]
print("not_encountered grid item count:", grid.count())
print("column of 4th card (expect 0, since 4 % 3 == 1... check item at index 3):",
      grid.getItemPosition(3) if grid.count() > 3 else "fewer than 4 cards")

# Confirm at least 3 columns are actually used once there are >= 3 entries
positions = [grid.getItemPosition(i) for i in range(min(grid.count(), 6))]
cols_used = sorted({p[1] for p in positions})
print("columns used (expect [0, 1, 2] once there are 3+ not_encountered engineers):", cols_used)

# Spot-check the accent color made it into the rendered HTML for an unlocked card
unlocked_grid = tab._section_grids["unlocked"]
if unlocked_grid.count() > 0:
    card = unlocked_grid.itemAt(0).widget()
    html = card.text()
    print("unlocked card contains green accent:", "#6BCB77" in html)
    print("unlocked card contains checkmark:", "✓" in html)
```

Fill in `engineer_progress` with two real names from `settings/engineer_requirements.json` (read that file to pick valid names — one with a `rank` of 1+ for the Unlocked case, one with only a `progress` string and no `rank` for the In Progress case) before running. Confirm: `not_encountered` has more than 3 entries and `columns used` prints `[0, 1, 2]`; the unlocked card's HTML contains both `#6BCB77` and `✓`. If the 4-value border-color shorthand doesn't visibly render a distinct left accent when actually looked at (open a screenshot via `tab.grab().save(...)` if unsure), note that as a concern in the task report rather than silently accepting it — the task reviewer should specifically check this.

- [ ] **Step 10: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: color-code Engineers tab by status and lay out cards in a 3-column grid"
```
