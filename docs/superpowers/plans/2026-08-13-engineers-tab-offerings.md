# Engineers Tab Offerings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the Engineers tab's sections (In Progress first, Unlocked last), tag each engineer card `[Ship]`/`[Suit & Weapons]` for which category they belong to, and add a one-line upgrade-count summary per card — all built from data already loaded, no new external sources.

**Architecture:** Two small cached-count methods added to the existing `EngineeringBlueprintTable` and `OdysseyEngineeringTable` classes (each already caches its JSON on load; the new counts get built alongside that existing cache-rebuild step, not recomputed per call). `_EngineersTab` in `edc/ui/panels/engineering_panel.py` consumes both counts to render the tag and summary line, and gets a new `odyssey_table` constructor parameter since it currently only has ship-side data.

**Tech Stack:** Python, PyQt6.

## Global Constraints

- `EngineeringBlueprintTable.engineer_blueprint_count(engineer_name: str) -> int` — count of distinct blueprint fdnames this engineer appears in `grade_engineers` for, at ANY grade (an engineer offering the same blueprint at multiple grades counts once, not once per grade).
- `OdysseyEngineeringTable.engineer_module_count(engineer_name: str) -> int` — count of distinct suit + weapon module keys this engineer appears in the module's `engineers` list for (flat, no per-grade split on this side).
- Both counts are built once per `_load()` call (i.e. once per file-mtime change, matching each class's existing cache-invalidation pattern), not recomputed on every method call.
- Section order becomes `in_progress`, `not_encountered`, `unlocked` (was `unlocked`, `in_progress`, `not_encountered`) — applies to both the header/grid creation loop in `__init__` and the population loop in `refresh()`.
- Tag format: `[Ship]` if `engineer_blueprint_count(name) > 0`; `[Suit & Weapons]` if `engineer_module_count(name) > 0`; both together render as `[Ship, Suit & Weapons]`; if both are zero, no tag at all.
- Summary line format: `f"{n} ship blueprint{'s' if n != 1 else ''}, {m} suit & weapon mod{'s' if m != 1 else ''}"` — omit the entire line if both counts are zero (not a "0 of everything" line).
- No new files.

---

## File Structure

- **Modify:** `edc/core/engineering_blueprints.py` — new `engineer_blueprint_count()` method + cache-building on `_load()`.
- **Modify:** `edc/core/odyssey_engineering.py` — new `engineer_module_count()` method + cache-building on `_load()`.
- **Modify:** `edc/ui/panels/engineering_panel.py` — `_EngineersTab` section reorder, new `odyssey_table` constructor param, tag + summary line in `_engineer_html`; `EngineeringPanel.__init__`'s `_EngineersTab(blueprint_table)` call site updated to pass `odyssey_table` through.
- **Test:** `tests/test_engineering_blueprints.py` (new), `tests/test_odyssey_engineering.py` (new) — neither class has existing tests; both get a small `tmp_path`-based fixture file, matching this repo's established `tmp_path` convention (see `tests/test_odyssey_farming_candidates.py`).

---

### Task 1: `EngineeringBlueprintTable.engineer_blueprint_count()`

**Files:**
- Modify: `edc/core/engineering_blueprints.py`
- Test: `tests/test_engineering_blueprints.py`

**Interfaces:**
- Produces: `EngineeringBlueprintTable.engineer_blueprint_count(engineer_name: str) -> int` — used by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engineering_blueprints.py`:

```python
"""Tests for EngineeringBlueprintTable.engineer_blueprint_count() -- counts
distinct blueprints an engineer offers at any grade, from real JSON on
disk (tmp_path), not mocks."""
import json

from edc.core.engineering_blueprints import EngineeringBlueprintTable


def _write_fixture(tmp_path, blueprints):
    data = {"last_updated": "2026-08-13", "blueprints": blueprints}
    (tmp_path / "engineering_blueprints.json").write_text(json.dumps(data), encoding="utf-8")


def test_counts_one_blueprint_offered_at_one_grade(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 1


def test_same_blueprint_at_multiple_grades_counts_once(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}, "2": {}, "3": {}},
            "grade_engineers": {
                "1": ["Felicity Farseer"],
                "2": ["Felicity Farseer"],
                "3": ["Felicity Farseer"],
            },
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 1


def test_counts_multiple_distinct_blueprints(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
        "armour_heavy": {
            "display_name": "Heavy Duty Armour",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 2


def test_engineer_with_no_offerings_is_zero(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("The Dweller") == 0


def test_no_data_file_returns_zero_for_everyone(tmp_path):
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engineering_blueprints.py -v`
Expected: every test FAILs with `AttributeError: 'EngineeringBlueprintTable' object has no attribute 'engineer_blueprint_count'`.

- [ ] **Step 3: Add the cache attribute and builder, and rebuild it inside `_load()`**

Re-read `edc/core/engineering_blueprints.py` fresh before editing (confirm it still matches the "before" blocks below — it was re-read immediately before this plan was written, but re-verify rather than assume).

Current `__init__` (relevant excerpt):

```python
    def __init__(self, settings_dir: Path, filename: str = "engineering_blueprints.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._blueprints: Dict[str, Dict[str, Any]] = {}
        self._materials: Dict[str, Dict[str, Any]] = {}
        self._engineer_locations: Dict[str, Dict[str, Any]] = {}
        self._engineer_requirements: Dict[str, Dict[str, str]] = {}
        self._requirements_mtime: Optional[float] = None
        self._load(force=True)
        self._load_requirements(force=True)
```

Add one new attribute, right after `self._engineer_locations`:

```python
    def __init__(self, settings_dir: Path, filename: str = "engineering_blueprints.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._blueprints: Dict[str, Dict[str, Any]] = {}
        self._materials: Dict[str, Dict[str, Any]] = {}
        self._engineer_locations: Dict[str, Dict[str, Any]] = {}
        self._engineer_blueprint_counts: Dict[str, int] = {}
        self._engineer_requirements: Dict[str, Dict[str, str]] = {}
        self._requirements_mtime: Optional[float] = None
        self._load(force=True)
        self._load_requirements(force=True)
```

Current `_load()`:

```python
    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._blueprints = {}
                self._materials = {}
                self._engineer_locations = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = None
            blueprints = {}
            materials = {}
            engineer_locations = {}
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = lu.strip() if isinstance(lu, str) and lu.strip() else None
                blueprints = data.get("blueprints") or {}
                materials = data.get("materials") or {}
                engineer_locations = data.get("engineer_locations") or {}

            self._blueprints = blueprints if isinstance(blueprints, dict) else {}
            self._materials = materials if isinstance(materials, dict) else {}
            self._engineer_locations = engineer_locations if isinstance(engineer_locations, dict) else {}
        except Exception:
            log.exception("Failed to load engineering_blueprints.json")
            self._blueprints = {}
            self._materials = {}
            self._engineer_locations = {}
            self.last_updated = None
            self._mtime = None
```

Replace with (adds a reset in both early-exit paths, and a rebuild call on the success path):

```python
    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._blueprints = {}
                self._materials = {}
                self._engineer_locations = {}
                self._engineer_blueprint_counts = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = None
            blueprints = {}
            materials = {}
            engineer_locations = {}
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = lu.strip() if isinstance(lu, str) and lu.strip() else None
                blueprints = data.get("blueprints") or {}
                materials = data.get("materials") or {}
                engineer_locations = data.get("engineer_locations") or {}

            self._blueprints = blueprints if isinstance(blueprints, dict) else {}
            self._materials = materials if isinstance(materials, dict) else {}
            self._engineer_locations = engineer_locations if isinstance(engineer_locations, dict) else {}
            self._engineer_blueprint_counts = self._build_engineer_blueprint_counts()
        except Exception:
            log.exception("Failed to load engineering_blueprints.json")
            self._blueprints = {}
            self._materials = {}
            self._engineer_locations = {}
            self._engineer_blueprint_counts = {}
            self.last_updated = None
            self._mtime = None
```

- [ ] **Step 4: Add the builder method and the public accessor**

Add these two methods directly after `_load()` (before `_load_requirements`):

```python
    def _build_engineer_blueprint_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for bp in self._blueprints.values():
            grade_engineers = bp.get("grade_engineers") or {}
            engineers_for_this_blueprint: set = set()
            for grade_list in grade_engineers.values():
                if isinstance(grade_list, list):
                    engineers_for_this_blueprint.update(n for n in grade_list if isinstance(n, str))
            for name in engineers_for_this_blueprint:
                counts[name] = counts.get(name, 0) + 1
        return counts
```

Add this public method at the end of the class (after `all_engineer_homes`):

```python
    def engineer_blueprint_count(self, engineer_name: str) -> int:
        """Number of distinct ship blueprints this engineer offers, at any grade."""
        self._load(force=False)
        return self._engineer_blueprint_counts.get(engineer_name, 0)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_engineering_blueprints.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all previously-passing tests plus these 5 new ones pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add edc/core/engineering_blueprints.py tests/test_engineering_blueprints.py
git commit -m "feat: add engineer_blueprint_count() to EngineeringBlueprintTable"
```

---

### Task 2: `OdysseyEngineeringTable.engineer_module_count()`

**Files:**
- Modify: `edc/core/odyssey_engineering.py`
- Test: `tests/test_odyssey_engineering.py`

**Interfaces:**
- Produces: `OdysseyEngineeringTable.engineer_module_count(engineer_name: str) -> int` — used by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_odyssey_engineering.py`:

```python
"""Tests for OdysseyEngineeringTable.engineer_module_count() -- counts
distinct suit + weapon modules an engineer offers, from real JSON on
disk (tmp_path), not mocks."""
import json

from edc.core.odyssey_engineering import OdysseyEngineeringTable


def _write_fixture(tmp_path, suit_modules=None, weapon_modules=None):
    data = {
        "last_updated": "2026-08-13",
        "suit_modules": suit_modules or {},
        "weapon_modules": weapon_modules or {},
    }
    (tmp_path / "odyssey_engineering.json").write_text(json.dumps(data), encoding="utf-8")


def test_counts_one_suit_module(tmp_path):
    _write_fixture(tmp_path, suit_modules={
        "extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 1


def test_counts_one_weapon_module(tmp_path):
    _write_fixture(tmp_path, weapon_modules={
        "clean_shot": {"display_name": "Clean Shot", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 1


def test_suit_and_weapon_modules_combine(tmp_path):
    _write_fixture(
        tmp_path,
        suit_modules={"extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]}},
        weapon_modules={"clean_shot": {"display_name": "Clean Shot", "engineers": ["Yarden Bond"]}},
    )
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 2


def test_engineer_with_no_offerings_is_zero(tmp_path):
    _write_fixture(tmp_path, suit_modules={
        "extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Hero Ferrari") == 0


def test_no_data_file_returns_zero_for_everyone(tmp_path):
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odyssey_engineering.py -v`
Expected: every test FAILs with `AttributeError: 'OdysseyEngineeringTable' object has no attribute 'engineer_module_count'`.

- [ ] **Step 3: Add the cache attribute and rebuild it inside `_load()`**

Re-read `edc/core/odyssey_engineering.py` fresh before editing.

Current `__init__` (relevant excerpt):

```python
    def __init__(self, settings_dir: Path, filename: str = "odyssey_engineering.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._suits: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._weapons: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._suit_modules: Dict[str, Dict[str, Any]] = {}
        self._weapon_modules: Dict[str, Dict[str, Any]] = {}
        self._load(force=True)
```

Add one new attribute:

```python
    def __init__(self, settings_dir: Path, filename: str = "odyssey_engineering.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._suits: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._weapons: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._suit_modules: Dict[str, Dict[str, Any]] = {}
        self._weapon_modules: Dict[str, Dict[str, Any]] = {}
        self._engineer_module_counts: Dict[str, int] = {}
        self._load(force=True)
```

Current `_load()`:

```python
    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._suits = {}
                self._weapons = {}
                self._suit_modules = {}
                self._weapon_modules = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = data.get("last_updated") if isinstance(data, dict) else None
            self._suits = (data.get("suits") or {}) if isinstance(data, dict) else {}
            self._weapons = (data.get("weapons") or {}) if isinstance(data, dict) else {}
            self._suit_modules = (data.get("suit_modules") or {}) if isinstance(data, dict) else {}
            self._weapon_modules = (data.get("weapon_modules") or {}) if isinstance(data, dict) else {}
        except Exception:
            log.exception("Failed to load odyssey_engineering.json")
            self._suits = {}
            self._weapons = {}
            self._suit_modules = {}
            self._weapon_modules = {}
            self.last_updated = None
            self._mtime = None
```

Replace with:

```python
    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._suits = {}
                self._weapons = {}
                self._suit_modules = {}
                self._weapon_modules = {}
                self._engineer_module_counts = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = data.get("last_updated") if isinstance(data, dict) else None
            self._suits = (data.get("suits") or {}) if isinstance(data, dict) else {}
            self._weapons = (data.get("weapons") or {}) if isinstance(data, dict) else {}
            self._suit_modules = (data.get("suit_modules") or {}) if isinstance(data, dict) else {}
            self._weapon_modules = (data.get("weapon_modules") or {}) if isinstance(data, dict) else {}
            self._engineer_module_counts = self._build_engineer_module_counts()
        except Exception:
            log.exception("Failed to load odyssey_engineering.json")
            self._suits = {}
            self._weapons = {}
            self._suit_modules = {}
            self._weapon_modules = {}
            self._engineer_module_counts = {}
            self.last_updated = None
            self._mtime = None
```

- [ ] **Step 4: Add the builder method and the public accessor**

Add this method directly after `_load()`:

```python
    def _build_engineer_module_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for modules in (self._suit_modules, self._weapon_modules):
            for rec in modules.values():
                engineers = rec.get("engineers") if isinstance(rec, dict) else None
                if not isinstance(engineers, list):
                    continue
                for name in engineers:
                    if isinstance(name, str):
                        counts[name] = counts.get(name, 0) + 1
        return counts
```

Add this public method at the end of the class (after `module_engineers`):

```python
    def engineer_module_count(self, engineer_name: str) -> int:
        """Number of distinct suit + weapon modules this engineer offers."""
        self._load(force=False)
        return self._engineer_module_counts.get(engineer_name, 0)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_odyssey_engineering.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all previously-passing tests plus these 5 new ones pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add edc/core/odyssey_engineering.py tests/test_odyssey_engineering.py
git commit -m "feat: add engineer_module_count() to OdysseyEngineeringTable"
```

---

### Task 3: Section reorder, category tag, and upgrade summary in `_EngineersTab`

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`

**Interfaces:**
- Consumes: `EngineeringBlueprintTable.engineer_blueprint_count(name: str) -> int` (Task 1), `OdysseyEngineeringTable.engineer_module_count(name: str) -> int` (Task 2).
- Produces: nothing consumed elsewhere — final task in this plan.

- [ ] **Step 1: Add `odyssey_table` to `_EngineersTab.__init__` and reorder the section tuple**

Re-read `edc/ui/panels/engineering_panel.py` fresh before editing — flagged frequently-stale by this project's CLAUDE.md, and this exact class was modified twice already today by earlier plans.

Current `_EngineersTab.__init__` (relevant excerpt):

```python
    def __init__(self, blueprint_table: EngineeringBlueprintTable, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._state = None
        self._last_sig = None
```

Replace with:

```python
    def __init__(self, blueprint_table: EngineeringBlueprintTable, odyssey_table: OdysseyEngineeringTable, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._odyssey = odyssey_table
        self._state = None
        self._last_sig = None
```

`OdysseyEngineeringTable` is already imported in this file (used by `_OdysseyEngineeringTab`) — no new import needed; confirm this is still true when you re-read the file.

Current section tuple in `__init__` (a few lines below):

```python
        self._section_grids: Dict[str, QGridLayout] = {}
        for key, label_text in (
            ("unlocked", "UNLOCKED"),
            ("in_progress", "IN PROGRESS"),
            ("not_encountered", "NOT ENCOUNTERED"),
        ):
```

Replace with (reordered, nothing else in this loop changes):

```python
        self._section_grids: Dict[str, QGridLayout] = {}
        for key, label_text in (
            ("in_progress", "IN PROGRESS"),
            ("not_encountered", "NOT ENCOUNTERED"),
            ("unlocked", "UNLOCKED"),
        ):
```

- [ ] **Step 2: Reorder the section tuple in `refresh()`**

Current:

```python
        for key in ("unlocked", "in_progress", "not_encountered"):
            grid = self._section_grids[key]
```

Replace with:

```python
        for key in ("in_progress", "not_encountered", "unlocked"):
            grid = self._section_grids[key]
```

- [ ] **Step 3: Add the category tag and upgrade summary in `_engineer_html`**

Current `_engineer_html` (relevant excerpt — the name line and the section right after the status line):

```python
        line = f'<span style="color:{accent["name_color"]};font-weight:700;">{self._esc(name)}</span>'
        if system_text:
            line += f' <span style="color:#4D96FF;font-size:12px;">— {self._esc(system_text)}{dist_text}</span>'
        line += (
            f'<br><span style="color:{accent["status_color"]};font-size:12px;">'
            f'{accent["check"]}{self._esc(status_text)}</span>'
        )

        for field_key, field_label in (
```

Replace with (adds the tag right after the name, and the summary line right after the status line, before the requirement fields loop; computes each count once and reuses it for both the tag and the summary):

```python
        ship_count = self._blueprints.engineer_blueprint_count(name)
        module_count = self._odyssey.engineer_module_count(name)

        tags = []
        if ship_count > 0:
            tags.append("Ship")
        if module_count > 0:
            tags.append("Suit & Weapons")
        tag_text = f" [{', '.join(tags)}]" if tags else ""

        line = (
            f'<span style="color:{accent["name_color"]};font-weight:700;">{self._esc(name)}</span>'
            f'<span style="color:#666666;font-weight:400;">{self._esc(tag_text)}</span>'
        )
        if system_text:
            line += f' <span style="color:#4D96FF;font-size:12px;">— {self._esc(system_text)}{dist_text}</span>'
        line += (
            f'<br><span style="color:{accent["status_color"]};font-size:12px;">'
            f'{accent["check"]}{self._esc(status_text)}</span>'
        )

        if ship_count or module_count:
            ship_word = "blueprint" if ship_count == 1 else "blueprints"
            mod_word = "mod" if module_count == 1 else "mods"
            summary = f"{ship_count} ship {ship_word}, {module_count} suit & weapon {mod_word}"
            line += f'<br><span style="color:#888888;font-size:12px;">{self._esc(summary)}</span>'

        for field_key, field_label in (
```

- [ ] **Step 4: Update the `EngineeringPanel.__init__` call site**

Current:

```python
        self._engineers_tab = _EngineersTab(blueprint_table)
```

Replace with:

```python
        self._engineers_tab = _EngineersTab(blueprint_table, odyssey_table)
```

- [ ] **Step 5: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass (this task adds no new tests — rendering-only change, per this tab's established convention).

- [ ] **Step 7: Headless visual verification**

Matching the previous plan's convention, write a scratch script (in this project's scratchpad, not committed) that instantiates the real `_EngineersTab` offscreen with real `EngineeringBlueprintTable`/`OdysseyEngineeringTable` instances pointed at `settings/`, a fake state with one Unlocked and one In Progress engineer (same approach as the last plan's verification step), calls `refresh()`, shows the widget, and confirms:

- `tab._section_grids` iteration order in the source (or just re-read the file) is `in_progress`, `not_encountered`, `unlocked` — confirm the header `QLabel` text at `content_layout` positions 0, 2, 4 (headers and grids alternate) reads "IN PROGRESS", "NOT ENCOUNTERED", "UNLOCKED" in that order top to bottom.
- Pick a real engineer known to offer at least one ship blueprint (e.g. check `settings/engineering_blueprints.json`'s `grade_engineers` entries for a name that appears there) and confirm their card's HTML contains `[Ship]` (or `[Ship, Suit & Weapons]` if they also appear in Odyssey module engineers) and a `ship blueprint` summary line with a nonzero count.
- Pick an engineer with zero entries in both `grade_engineers` and Odyssey `engineers` lists (if one exists in the real data — check first) and confirm their card's HTML contains no `[` tag at all and no summary line.

Report the actual printed output, not just a description of what should happen.

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: reorder Engineers tab sections and show Ship/Suit\&Weapons tags with upgrade counts"
```
