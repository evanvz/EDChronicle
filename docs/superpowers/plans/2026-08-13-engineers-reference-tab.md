# Engineers Reference Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Engineers" sub-tab in the Engineering panel listing every in-game engineer with discovery/meeting/unlock/referral requirement text, grouped by the player's real current status (Unlocked / In Progress / Not Encountered) using data EDChronicle already tracks.

**Architecture:** A new hand-curated data file (`settings/engineer_requirements.json`) loaded by the existing `EngineeringBlueprintTable` class (extended, not replaced — it already owns the matching `engineer_locations` data these entries join against by name). A new `_EngineersTab` widget in `engineering_panel.py`, using this codebase's established scrollable-rich-text-sections pattern (already proven in `intel_panel.py`'s farming guide) rather than one real Qt widget per engineer — less code, no per-refresh widget churn.

**Tech Stack:** Python, PyQt6.

## Global Constraints

- `settings/engineer_requirements.json` keys must exactly match the existing `engineer_locations` keys in `settings/engineering_blueprints.json` (the join key) — in particular, use `"Tod 'The Blaster' McQuinn"` (single quotes, matching the existing `engineer_locations` entry exactly) NOT the source material's double-quote rendering `Tod "The Blaster" McQuinn` — confirmed as the one real name-string mismatch between the two data sources during this plan's own research pass.
- Per-engineer entries have 2-4 fields: `discover` (always present), `meet` (present for the "classic" unlock pattern — meet a condition, then provide materials), `unlock` (always present — either the classic material-provision step, or the newer Odyssey-era "complete N missions/sell N goods" step), `referral` (present only for the newer Odyssey-era engineers, an additional provide-this-item step after `unlock`). A missing field is omitted from the JSON entirely, never stored as an empty string — the UI skips rendering any field that isn't present.
- Status derivation reuses the exact logic already established in this file's existing `_refresh_engineer_table()` methods (both tabs) for reading `state.engineer_progress` — do not invent new status logic:
  - No entry for this engineer name in `state.engineer_progress` → **Not Encountered**.
  - Entry exists, `rank` is an `int >= 1` → **Unlocked — Rank {rank}**.
  - Entry exists, `rank` is `0`/`None`/missing but `progress` is a non-empty string → **{progress} — not yet unlocked** (goes in the In Progress group).
  - Anything else (defensive fallback) → **Not Encountered**.
- No new database table, no new journal parsing, no new persistence — this tab is a pure read of `state.engineer_progress` (already populated), `state.system_x/y/z` (already populated), and the two already-loaded/extended settings files.
- No new automated tests — pure reference/display feature with no new business logic, matches this file's established convention (every other Engineering panel change this session verified live, not synthetically tested).

---

## File Structure

- **Create:** `settings/engineer_requirements.json` — 38 entries, one per engineer.
- **Modify:** `edc/core/engineering_blueprints.py` — `EngineeringBlueprintTable` gains a second file load (`engineer_requirements.json`) and a new `engineer_requirements(name)` accessor.
- **Modify:** `edc/ui/panels/engineering_panel.py` — new `_EngineersTab` class, wired into `EngineeringPanel`'s tab widget and `refresh()`.

---

### Task 1: Data file + `EngineeringBlueprintTable` extension

**Files:**
- Create: `settings/engineer_requirements.json`
- Modify: `edc/core/engineering_blueprints.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `EngineeringBlueprintTable.engineer_requirements(engineer_name: str) -> Optional[Dict[str, str]]` (keys among `"discover"`, `"meet"`, `"unlock"`, `"referral"`, whichever are present for that engineer) — Task 2 calls this by exact name

- [ ] **Step 1: Create the data file**

Create `settings/engineer_requirements.json` with exactly this content:

```json
{
  "last_updated": "2026-08-13",
  "source": "User-supplied compilation of official/community engineer unlock data",
  "engineers": {
    "Felicity Farseer": {
      "discover": "Public data sources.",
      "meet": "Gain exploration rank Scout or higher.",
      "unlock": "Provide 1 unit of Meta Alloys."
    },
    "Juri Ishmaak": {
      "discover": "From Felicity Farseer (grade 3-4).",
      "meet": "Claim more than 50 federal combat bonds.",
      "unlock": "Provide 100,000 or 1,000,000 credits worth of federal combat bonds (the amount needed depends on the currently unknown conditions)."
    },
    "Colonel Bris Dekker": {
      "discover": "From Juri Ishmaak (grade 3-4).",
      "meet": "Friendly with the Federation.",
      "unlock": "Provide 1,000,000 or 10,000,000 credits worth of federal combat bonds (the amount needed depends on the currently unknown conditions)."
    },
    "The Sarge": {
      "discover": "From Juri Ishmaak (grade 3-4).",
      "meet": "Gain rank Midshipman or higher with the Federal Navy.",
      "unlock": "Provide 50 units of Aberrant Shield Pattern Analysis."
    },
    "Elvira Martuuk": {
      "discover": "Public knowledge.",
      "meet": "Attain a maximum distance from your career start location of at least 300 light years.",
      "unlock": "Provide 3 units of Soontill Relics."
    },
    "Mel Brandon": {
      "discover": "From Elvira Martuuk (grade 3-4).",
      "meet": "Gain invitation from Colonia Council.",
      "unlock": "Provide 100,000 credits worth of bounty vouchers."
    },
    "Zacariah Nemo": {
      "discover": "From Elvira Martuuk (grade 3-4).",
      "meet": "Gain invitation from Party of Yoru.",
      "unlock": "Provide 25 units of Xihe Companions."
    },
    "Marco Qwent": {
      "discover": "From Elvira Martuuk (grade 3-4).",
      "meet": "Gain invitation from Sirius Corporation.",
      "unlock": "Provide 25 units of Modular Terminals."
    },
    "Chloe Sedesi": {
      "discover": "From Marco Qwent (grade 3-4).",
      "meet": "Attain a maximum distance from your career start location of at least 5,000 light years.",
      "unlock": "Provide 25 units of Sensor Fragments."
    },
    "Lori Jameson": {
      "discover": "From Marco Qwent (grade 3-4).",
      "meet": "Gain combat rank Dangerous or higher.",
      "unlock": "Provide 25 units of Kongga Ale."
    },
    "Professor Palin": {
      "discover": "From Marco Qwent (grade 3-4).",
      "meet": "Attain a maximum distance from your career start location of at least 5,000 light years.",
      "unlock": "Provide 25 units of Sensor Fragments."
    },
    "The Dweller": {
      "discover": "Common knowledge.",
      "meet": "Deal with at least 5 black markets.",
      "unlock": "Pay 500,000 credits."
    },
    "Marsha Hicks": {
      "discover": "From The Dweller (grade 3-4).",
      "meet": "Gain exploration rank Surveyor or higher.",
      "unlock": "Provide 10 units of mined Osmium."
    },
    "Lei Cheung": {
      "discover": "From The Dweller (grade 3-4).",
      "meet": "You have traded in over 50 markets.",
      "unlock": "Provide 200 units of Gold."
    },
    "Ram Tah": {
      "discover": "From Lei Cheung (grade 3-4).",
      "meet": "Gain exploration rank Surveyor or higher.",
      "unlock": "Provide 50 units of Classified Scan Databanks."
    },
    "Tod 'The Blaster' McQuinn": {
      "discover": "Common knowledge.",
      "meet": "Earn more than 15 bounty vouchers.",
      "unlock": "Provide 100,000 credits worth of bounty vouchers."
    },
    "Petra Olmanova": {
      "discover": "From Tod 'The Blaster' McQuinn (grade 3-4).",
      "meet": "Gain combat rank Expert or higher.",
      "unlock": "Provide 200 units of Progenitor Cells."
    },
    "Selene Jean": {
      "discover": "From Tod 'The Blaster' McQuinn (grade 3-4).",
      "meet": "Mine at least 500 tons of ore.",
      "unlock": "Provide 10 units of mined Painite."
    },
    "Bill Turner": {
      "discover": "From Selene Jean (grade 3-4).",
      "meet": "Gain Friendly status with the Alliance and Allied reputation with the Alioth Independents to get a permit to access the Alioth star system.",
      "unlock": "Provide 50 units of Bromellite."
    },
    "Didi Vatermann": {
      "discover": "From Selene Jean (grade 3-4).",
      "meet": "Gain trade rank Merchant or higher.",
      "unlock": "Provide 50 units of Lavian Brandy."
    },
    "Liz Ryder": {
      "discover": "Public sources.",
      "meet": "Gain Cordial or Friendly status with Eurybia Blue Mafia.",
      "unlock": "Provide 200 units of Landmines."
    },
    "Etienne Dorn": {
      "discover": "From Liz Ryder (grade 3-4).",
      "meet": "Gain trade rank Dealer or higher.",
      "unlock": "Provide 25 units of Occupied Escape Pods."
    },
    "Hera Tani": {
      "discover": "From Liz Ryder (grade 3-4).",
      "meet": "Gain rank Outsider or higher with the Empire.",
      "unlock": "Provide 50 units of Kamitra Cigars."
    },
    "Broo Tarquin": {
      "discover": "From Hera Tani (grade 3-4).",
      "meet": "Gain combat rank Competent or higher.",
      "unlock": "Provide 50 units of Fujin Tea."
    },
    "Tiana Fortune": {
      "discover": "From Hera Tani (grade 3-4).",
      "meet": "Friendly with the Empire.",
      "unlock": "Provide 50 units of Decoded Emission Data."
    },
    "Hero Ferrari": {
      "discover": "Common knowledge.",
      "unlock": "Complete 10 surface conflict zones.",
      "referral": "Provide 5 Settlement Defence Plans."
    },
    "Wellington Beck": {
      "discover": "From Hero Ferrari.",
      "unlock": "Sell a total of 15 Multimedia Entertainment, Classic Entertainment and Cat media to bartenders.",
      "referral": "Provide 5 units of Insight Entertainment suites."
    },
    "Uma Laszlo": {
      "discover": "From Wellington Beck.",
      "unlock": "Reach Unfriendly reputation or lower with Sirius Corporation."
    },
    "Jude Navarro": {
      "discover": "Common knowledge.",
      "unlock": "Complete 10 Restore or Reactivation missions.",
      "referral": "Provide 5 units of Genetic Repair Meds."
    },
    "Terra Velasquez": {
      "discover": "From Jude Navarro.",
      "unlock": "Complete 6 Covert theft and Covert heist missions.",
      "referral": "Provide 15 Financial projections."
    },
    "Oden Geiger": {
      "discover": "From Terra Velasquez.",
      "unlock": "Sell a total of 20 Biological sample, Employee genetic data and Genetic research to bartenders."
    },
    "Domino Green": {
      "discover": "Common knowledge.",
      "unlock": "Travel at least 100 light years in shuttles.",
      "referral": "Provide 5 doses of Push."
    },
    "Kit Fowler": {
      "discover": "From Domino Green.",
      "unlock": "Sell 5 Opinion polls to bartenders.",
      "referral": "Provide 5 units of Surveillance equipment."
    },
    "Yarden Bond": {
      "discover": "From Kit Fowler.",
      "unlock": "Sell 5 Smear campaign plans to bartenders."
    },
    "Eleanor Bresa": {
      "discover": "Common knowledge.",
      "unlock": "Visit 5 settlements in the Colonia system.",
      "referral": "Provide 10 Digital Designs."
    },
    "Rosa Dayette": {
      "discover": "Common knowledge.",
      "unlock": "Sell a total of 10 Culinary Recipes or Cocktail Recipes to stations in Colonia.",
      "referral": "Provide 10 units of Manufacturing Instructions data."
    },
    "Baltanos": {
      "discover": "Common knowledge.",
      "unlock": "Reach Friendly reputation with the Colonia Council.",
      "referral": "Provide 10 Faction Associates data."
    },
    "Yi Shen": {
      "discover": "From Baltanos, Eleanor Bresa and Rosa Dayette.",
      "unlock": "Complete referral tasks for Baltanos, Eleanor Bresa and Rosa Dayette."
    }
  }
}
```

- [ ] **Step 2: Validate the JSON is well-formed**

Run: `python -c "import json; json.load(open('settings/engineer_requirements.json', encoding='utf-8'))"`
Expected: no output, exit code 0.

- [ ] **Step 3: Validate every key matches `engineer_locations`**

Run:
```
python -c "
import json
loc = json.load(open('settings/engineering_blueprints.json', encoding='utf-8'))['engineer_locations']
req = json.load(open('settings/engineer_requirements.json', encoding='utf-8'))['engineers']
print('in requirements but not locations:', sorted(set(req) - set(loc)))
print('in locations but not requirements:', sorted(set(loc) - set(req)))
"
```
Expected: both lines print `[]` — every name matches exactly between the two files, confirming the join key is correct. If either set is non-empty, fix the mismatched name(s) in `engineer_requirements.json` before continuing (this project's CLAUDE.md flags exact-name joins as a common source of silent bugs — do not proceed with a mismatch).

- [ ] **Step 4: Extend `EngineeringBlueprintTable` to load the second file**

Re-read `edc/core/engineering_blueprints.py` fresh. In `EngineeringBlueprintTable.__init__`, directly after `self._engineer_locations: Dict[str, Dict[str, Any]] = {}`, add:

```python
        self._engineer_requirements: Dict[str, Dict[str, str]] = {}
        self._requirements_mtime: Optional[float] = None
```

Directly after `self._load(force=True)` (still inside `__init__`), add:

```python
        self._load_requirements(force=True)
```

Add a new method, directly after the existing `_load()` method:

```python
    def _load_requirements(self, force: bool = False) -> None:
        path = self.path.parent / "engineer_requirements.json"
        try:
            if not path.exists():
                self._engineer_requirements = {}
                self._requirements_mtime = None
                return

            m = path.stat().st_mtime
            if (not force) and (self._requirements_mtime is not None) and (m == self._requirements_mtime):
                return

            data = json.loads(path.read_text(encoding="utf-8"))
            self._requirements_mtime = m
            engineers = data.get("engineers") if isinstance(data, dict) else None
            self._engineer_requirements = engineers if isinstance(engineers, dict) else {}
        except Exception:
            log.exception("Failed to load engineer_requirements.json")
            self._engineer_requirements = {}
            self._requirements_mtime = None
```

Add a new public accessor, directly after the existing `engineer_home()` method:

```python
    def engineer_requirements(self, engineer_name: str) -> Optional[Dict[str, str]]:
        """Returns the {"discover","meet","unlock","referral"} subset present
        for this engineer, or None if unknown. Missing fields are simply
        absent from the dict, not empty strings."""
        self._load_requirements(force=False)
        rec = self._engineer_requirements.get(engineer_name)
        return rec if isinstance(rec, dict) else None

    def all_engineer_names(self) -> List[str]:
        """Every known engineer name, sourced from engineer_locations (the
        superset -- every entry in engineer_requirements is expected to
        also appear here, per this file's join-key requirement)."""
        self._load(force=False)
        return sorted(self._engineer_locations.keys())
```

- [ ] **Step 5: Byte-compile check**

Run: `python -m py_compile edc/core/engineering_blueprints.py`
Expected: no output, exit code 0.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all existing tests still pass (this task adds no new automated tests).

- [ ] **Step 7: Quick interpreter sanity check**

Run:
```
python -c "
from pathlib import Path
from edc.core.engineering_blueprints import EngineeringBlueprintTable
t = EngineeringBlueprintTable(Path('settings'))
print(len(t.all_engineer_names()), 'engineers')
print(t.engineer_requirements('Felicity Farseer'))
print(t.engineer_requirements('Hero Ferrari'))
print(t.engineer_requirements('Yarden Bond'))
print(t.engineer_home('Felicity Farseer'))
"
```
Expected: `38 engineers`; Felicity Farseer's dict has `discover`/`meet`/`unlock` keys; Hero Ferrari's has `discover`/`unlock`/`referral` (no `meet`); Yarden Bond's has only `discover`/`unlock` (no `meet`, no `referral`); `engineer_home` returns a real `{"system_name","x","y","z"}` dict, confirming the two files' data joins correctly by name.

- [ ] **Step 8: Commit**

```bash
git add settings/engineer_requirements.json edc/core/engineering_blueprints.py
git commit -m "feat: add engineer discovery/unlock requirements data"
```

---

### Task 2: Engineers reference sub-tab

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`

**Interfaces:**
- Consumes: `EngineeringBlueprintTable.engineer_requirements(name) -> Optional[Dict[str, str]]`, `EngineeringBlueprintTable.all_engineer_names() -> List[str]`, `EngineeringBlueprintTable.engineer_home(name) -> Optional[Dict[str, Any]]` (all from Task 1); `state.engineer_progress`, `state.system_x/y/z` (already populated elsewhere, unchanged by this plan)
- Produces: nothing consumed by other tasks — this is the final task

- [ ] **Step 1: Add `QScrollArea` to the imports**

Re-read `edc/ui/panels/engineering_panel.py` fresh (flagged frequently-stale by this project's CLAUDE.md). Add `QScrollArea` to the existing `from PyQt6.QtWidgets import (...)` block if not already present (this file currently uses `QTableWidget`-based master-detail layouts throughout and does not yet import `QScrollArea` — confirm by checking the current import list before assuming).

- [ ] **Step 2: Add the `_EngineersTab` class**

Add a new class directly after `_OdysseyEngineeringTab` (at the end of the file, or wherever that class's definition currently ends — re-read to confirm placement):

```python
class _EngineersTab(QWidget):
    """Reference list of every in-game engineer -- discovery/meeting/
    unlock/referral requirements, grouped by the player's real current
    status (state.engineer_progress, already tracked elsewhere in this
    app). Advisory only; requirement text is static reference data, not
    derived from live journal state beyond the overall unlock status."""

    def __init__(self, blueprint_table: EngineeringBlueprintTable, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._state = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        root.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(8, 6, 8, 8)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

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

    def _esc(self, t) -> str:
        return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _status_for(self, name: str):
        """Returns (group_key, status_text) for an engineer name, per this
        plan's Global Constraints status-derivation rule."""
        progress = getattr(self._state, "engineer_progress", None) or {} if self._state else {}
        rec = progress.get(name)
        if not rec:
            return "not_encountered", "Not Encountered"
        rank = rec.get("rank")
        if isinstance(rank, int) and rank >= 1:
            return "unlocked", f"Unlocked — Rank {rank}"
        prog = rec.get("progress")
        if prog:
            return "in_progress", f"{prog} — not yet unlocked"
        return "not_encountered", "Not Encountered"

    def _engineer_html(self, name: str, status_text: str) -> str:
        req = self._blueprints.engineer_requirements(name) or {}
        home = self._blueprints.engineer_home(name)

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

    def refresh(self, state) -> None:
        self._state = state
        names = self._blueprints.all_engineer_names()

        grouped: Dict[str, List[str]] = {"unlocked": [], "in_progress": [], "not_encountered": []}
        statuses: Dict[str, str] = {}
        for name in names:
            group, status_text = self._status_for(name)
            grouped[group].append(name)
            statuses[name] = status_text

        for key in ("unlocked", "in_progress", "not_encountered"):
            entries = sorted(grouped[key])
            html = "".join(self._engineer_html(name, statuses[name]) for name in entries)
            self._sections[key].setText(
                html if html else
                '<span style="color:#444444;font-size:12px;">None.</span>'
            )
```

- [ ] **Step 3: Wire the new tab into `EngineeringPanel`**

In `EngineeringPanel.__init__`, directly after the existing `self._odyssey_tab = _OdysseyEngineeringTab(...)` line, add:

```python
        self._engineers_tab = _EngineersTab(blueprint_table)
```

Directly after `self._tabs.addTab(self._odyssey_tab, "Suits & Weapons")`, add:

```python
        self._tabs.addTab(self._engineers_tab, "Engineers")
```

In `EngineeringPanel.refresh()`, directly after `self._odyssey_tab.refresh(state)`, add:

```python
        self._engineers_tab.refresh(state)
```

- [ ] **Step 4: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all tests still pass (this task adds no new automated tests, matching this project's convention for UI wiring).

- [ ] **Step 6: Visual + live verification**

Launch the app (or a headless `QT_QPA_PLATFORM=offscreen` smoke check if a full launch isn't available), open the Engineering tab:
- Confirm a new "Engineers" tab appears alongside Ships and Suits & Weapons.
- Confirm all 38 engineers render across the three sections, with no engineer appearing twice or missing.
- Confirm an engineer you've actually unlocked in-game (if any) shows in the Unlocked section with the correct rank.
- Confirm discover/meet/unlock/referral text renders correctly for a classic-pattern engineer (e.g. Felicity Farseer — discover/meet/unlock, no referral) and a newer-pattern one (e.g. Hero Ferrari — discover/unlock/referral, no meet).
- Confirm distance shown for a known engineer matches the distance already shown for that same engineer in the existing "Available From" table on the Ships tab (cross-check using the same underlying `engineer_home()` data).

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: add Engineers reference sub-tab to Engineering panel"
```
