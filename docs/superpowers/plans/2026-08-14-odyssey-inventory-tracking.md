# Odyssey Inventory Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Odyssey on-foot material tracking so held-material counts and display names update correctly after bartender trades and other backpack/ship-locker changes, across all four real inventory categories (Items, Components, Data, Consumables), combining both the Ship Locker and Backpack pools.

**Architecture:** Mirrors this codebase's existing, proven `Cargo.json` re-read pattern (`MainWindow._load_cargo_inventory()`) for two more journal quirks: `ShipLocker` and `Backpack` both fire as bare notification events whose real data lives in companion JSON files (`ShipLocker.json`, `Backpack.json`), not inline in the journal. `BackpackChange` is different — a genuinely incremental event carrying `Added`/`Removed` deltas directly — handled in the event engine's handler chain like the existing `MaterialCollected`/`MaterialDiscarded` handlers. A pre-existing, unrelated field-name bug (the ShipLocker handler writes to `shiplocker_items_loc`, but every UI consumer reads `shiplocker_localised` — confirmed nothing anywhere reads `shiplocker_items_loc`) is fixed as part of this same investigation, since it directly contributes to the reported "material names wrong" symptom.

**Tech Stack:** Python, PyQt6, stdlib `json`.

## Global Constraints

- `ShipLocker.json`/`Backpack.json` each have four top-level category arrays: `Items`, `Components`, `Data`, `Consumables` — confirmed live from the user's actual game files. All four must be parsed and merged into one flat counts/localised dict pair per pool (a material symbol only ever appears in one category, so merging via `dict.update` is collision-free).
- `state.shiplocker_items_loc` is dead — written by the `ShipLocker` handler, read by nothing anywhere in the codebase (confirmed via repo-wide grep). The handler must write to `state.shiplocker_localised` instead (what both `engineering_panel.py` and `inventory_panel.py` actually read), and the dead field is removed from `state.py` entirely.
- New `state.backpack_items`/`state.backpack_localised` fields, same shape as the ship-locker pair.
- `Backpack.json` is always re-read from disk on every `Backpack` event, not conditionally on whether the event happens to carry inline data — this matches the existing `Cargo`/`ShipLocker` precedent's robustness (cheap file read, never trust journal-inline data being present).
- `BackpackChange`'s `Added`/`Removed` items carry a `Type` field ("Consumable"/"Component"/"Item"), not `Category` — but since `backpack_items` is a single flat dict (not split by category), `Type` is not used to gate anything, only `Name`/`Count`/`Name_Localised` matter.
- `_OdysseyEngineeringTab._held_count()` (`edc/ui/panels/engineering_panel.py`) must sum ShipLocker's and Backpack's held count for a symbol, not ShipLocker alone.
- No raw category/type string ("Item"/"Component"/"Data"/"Consumable") is currently displayed anywhere in the Odyssey-related UI (confirmed via grep) — there is no code to change for "friendlier category labels" right now; noted here so this isn't silently dropped, but no task exists for it since there's nothing to fix.
- No schema changes, no new external dependencies.

---

## File Structure

- **Modify:** `edc/core/state.py` — remove dead `shiplocker_items_loc`, add `backpack_items`/`backpack_localised`.
- **Modify:** `edc/engine/handlers/inventory.py` — fix the `ShipLocker` handler's field-name bug, add `BackpackChange` handling.
- **Modify:** `edc/ui/main_window.py` — new `_load_shiplocker_inventory()` (extended to all 4 categories) and `_load_backpack_inventory()`, both wired to their bare journal events.
- **Modify:** `edc/ui/panels/engineering_panel.py` — `_held_count()`/`_material_name()` combine both pools.
- **Test:** `tests/test_odyssey_inventory.py` (new).

---

### Task 1: Fix the `shiplocker_items_loc`/`shiplocker_localised` field-name bug

**Files:**
- Modify: `edc/core/state.py`
- Modify: `edc/engine/handlers/inventory.py`
- Test: `tests/test_odyssey_inventory.py`

**Interfaces:**
- Produces: `state.shiplocker_localised` becomes the one real localised-name field the `ShipLocker` handler writes to — consumed already by `engineering_panel.py`/`inventory_panel.py` (unchanged in this task), and by Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_odyssey_inventory.py`:

```python
"""Tests for Odyssey on-foot inventory tracking -- ShipLocker/Backpack
handlers and file re-reads. Uses a real EventEngine + GameState (not
mocks), matching this repo's established testing convention."""
from pathlib import Path

import pytest

from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.engine.handlers import inventory


@pytest.fixture
def engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_shiplocker_handler_writes_localised_name_to_shiplocker_localised(engine):
    event = {
        "event": "ShipLocker",
        "Items": [
            {"Name": "graphene", "Name_Localised": "Graphene", "Count": 3},
        ],
    }
    handled = inventory.handle(engine, "ShipLocker", event, [])
    assert handled is True
    assert engine.state.shiplocker_items == {"graphene": 3}
    assert engine.state.shiplocker_localised == {"graphene": "Graphene"}


def test_shiplocker_items_loc_field_no_longer_exists(engine):
    assert not hasattr(engine.state, "shiplocker_items_loc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: `test_shiplocker_handler_writes_localised_name_to_shiplocker_localised` FAILs (asserts on `shiplocker_localised`, which is currently never written by the handler, so it stays `{}`); `test_shiplocker_items_loc_field_no_longer_exists` FAILs (the field currently still exists).

- [ ] **Step 3: Remove the dead field from `state.py`**

Re-read `edc/core/state.py` fresh before editing (confirm it still matches — re-read immediately before this plan was written). Current code:

```python
    # Odyssey (on-foot) inventory snapshot (journal-derived)
    shiplocker_items: Dict[str, int] = field(default_factory=dict)        # internal name -> count
    shiplocker_localised: Dict[str, str] = field(default_factory=dict)    # internal name -> display
    shiplocker_last_update: Optional[str] = None                          # journal timestamp

    # Handler split expects this name (alias)
    shiplocker_items_loc: Dict[str, str] = field(default_factory=dict)
```

Replace with (drops the dead alias field entirely — confirmed via repo-wide grep that nothing reads it):

```python
    # Odyssey (on-foot) inventory snapshot (journal-derived)
    shiplocker_items: Dict[str, int] = field(default_factory=dict)        # internal name -> count
    shiplocker_localised: Dict[str, str] = field(default_factory=dict)    # internal name -> display
    shiplocker_last_update: Optional[str] = None                          # journal timestamp
```

- [ ] **Step 4: Fix the handler's write target**

Re-read `edc/engine/handlers/inventory.py` fresh before editing. Current code:

```python
    elif name == "ShipLocker":
        # Odyssey storage
        locker = event.get("Items")
        if locker is not None:
            engine.state.shiplocker_items, engine.state.shiplocker_items_loc = engine._parse_shiplocker_items(locker)
        return True
```

Replace with (writes to `shiplocker_localised`, the field every consumer actually reads):

```python
    elif name == "ShipLocker":
        # Odyssey storage
        locker = event.get("Items")
        if locker is not None:
            engine.state.shiplocker_items, engine.state.shiplocker_localised = engine._parse_shiplocker_items(locker)
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all previously-passing tests plus these 2 new ones pass — no regressions (the dead field's removal must not break anything else; the earlier repo-wide grep found no other reference).

- [ ] **Step 7: Commit**

```bash
git add edc/core/state.py edc/engine/handlers/inventory.py tests/test_odyssey_inventory.py
git commit -m "fix: write ShipLocker localised names to the field the UI actually reads"
```

---

### Task 2: Re-read `ShipLocker.json` on the bare event, all four categories

**Files:**
- Modify: `edc/ui/main_window.py`
- Test: `tests/test_odyssey_inventory.py`

**Interfaces:**
- Consumes: `EventEngine._parse_shiplocker_items(items) -> tuple[Dict[str, int], Dict[str, str]]` (existing, unchanged).
- Produces: `MainWindow._load_shiplocker_inventory()` — used nowhere outside this task, wired directly to the `ShipLocker` event name inside `MainWindow`'s own event-dispatch method.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_odyssey_inventory.py`:

```python
import json


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_parse_shiplocker_items_merges_all_four_categories(engine):
    # This directly exercises the merge logic Task 2's
    # _load_shiplocker_inventory() will use -- four separate category
    # lists, each parsed via the existing _parse_shiplocker_items(),
    # combined into one flat pair with no collisions.
    counts: dict = {}
    loc: dict = {}
    for category_items in (
        [{"Name": "graphene", "Name_Localised": "Graphene", "Count": 3}],
        [{"Name": "rdx", "Name_Localised": "RDX", "Count": 5}],
        [{"Name": "biometricdata", "Name_Localised": "Biometric Data", "Count": 1}],
        [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
    ):
        c, l = engine._parse_shiplocker_items(category_items)
        counts.update(c)
        loc.update(l)
    assert counts == {"graphene": 3, "rdx": 5, "biometricdata": 1, "healthpack": 2}
    assert loc == {"graphene": "Graphene", "rdx": "RDX", "biometricdata": "Biometric Data", "healthpack": "Medkit"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: this test actually PASSES already, since it only exercises the existing, unchanged `_parse_shiplocker_items()` directly — this step confirms the merge logic itself is correct before wiring it into `MainWindow`. (This step deliberately verifies a passing baseline, not a failing one — the real integration point, `_load_shiplocker_inventory()`, doesn't exist yet and is added in Step 3.)

- [ ] **Step 3: Add `_load_shiplocker_inventory()`**

Re-read `edc/ui/main_window.py` fresh before editing (flagged frequently-stale by this project's CLAUDE.md). Find `_load_cargo_inventory()` (re-confirm its exact current location — it was re-read immediately before this plan was written) and add this new method directly after it:

```python
    def _load_shiplocker_inventory(self):
        """
        Reads ShipLocker.json -- per the journal manual, only the FIRST
        "ShipLocker" event in a session carries the Items array inline;
        every subsequent one is just a bare notification that the file
        changed, so this must be re-read from disk every time to stay
        current (same reasoning as _load_cargo_inventory() above). The
        file has four category arrays -- Items, Components, Data,
        Consumables -- all four are combined into one flat counts/
        localised pair, matching how _OdysseyEngineeringTab._held_count()
        expects a single dict (a material symbol only ever appears in one
        category, so merging is collision-free).
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        path = Path(journal_dir) / "ShipLocker.json"
        try:
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read ShipLocker.json")
            return

        if not isinstance(data, dict):
            return

        counts: dict = {}
        loc: dict = {}
        for category in ("Items", "Components", "Data", "Consumables"):
            c, l = self.engine._parse_shiplocker_items(data.get(category))
            counts.update(c)
            loc.update(l)
        self.state.shiplocker_items = counts
        self.state.shiplocker_localised = loc
```

- [ ] **Step 4: Wire it to the `ShipLocker` event**

Re-read the current event-dispatch method fresh (find the `if name == "Cargo":` block — it was at approximately line 2037 when last read, re-confirm). Current code:

```python
        if name == "Cargo":
            # Only the FIRST "Cargo" event in a session carries the
            # Inventory array inline — every subsequent one is just a bare
            # notification that Cargo.json changed (confirmed in the
            # journal manual), so the file itself must be re-read each time.
            self._load_cargo_inventory()
            self._refresh_market()

        if name == "EngineerProgress":
```

Replace with (adds a new `ShipLocker` block between the existing `Cargo` and `EngineerProgress` blocks — do not alter either of those):

```python
        if name == "Cargo":
            # Only the FIRST "Cargo" event in a session carries the
            # Inventory array inline — every subsequent one is just a bare
            # notification that Cargo.json changed (confirmed in the
            # journal manual), so the file itself must be re-read each time.
            self._load_cargo_inventory()
            self._refresh_market()

        if name == "ShipLocker":
            # Same journal quirk as Cargo above, and the same fix.
            self._load_shiplocker_inventory()
            self._refresh_engineering()

        if name == "EngineerProgress":
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: all tests so far PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 7: Byte-compile check**

Run: `python -m py_compile edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add edc/ui/main_window.py tests/test_odyssey_inventory.py
git commit -m "feat: re-read ShipLocker.json on the bare event, covering all four material categories"
```

---

### Task 3: Backpack tracking — `Backpack.json` re-read + `BackpackChange` deltas

**Files:**
- Modify: `edc/core/state.py`
- Modify: `edc/engine/handlers/inventory.py`
- Modify: `edc/ui/main_window.py`
- Test: `tests/test_odyssey_inventory.py`

**Interfaces:**
- Produces: `state.backpack_items: Dict[str, int]`, `state.backpack_localised: Dict[str, str]` — consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odyssey_inventory.py`:

```python
def test_backpack_fields_exist_on_state():
    state = GameState()
    assert state.backpack_items == {}
    assert state.backpack_localised == {}


def test_backpackchange_added_increments_backpack_items(engine):
    event = {
        "event": "BackpackChange",
        "Added": [
            {"Name": "healthpack", "Name_Localised": "Medkit", "OwnerID": 0, "Count": 2, "Type": "Consumable"},
        ],
    }
    handled = inventory.handle(engine, "BackpackChange", event, [])
    assert handled is True
    assert engine.state.backpack_items == {"healthpack": 2}
    assert engine.state.backpack_localised == {"healthpack": "Medkit"}


def test_backpackchange_removed_decrements_and_removes_at_zero(engine):
    engine.state.backpack_items = {"healthpack": 2}
    engine.state.backpack_localised = {"healthpack": "Medkit"}
    event = {
        "event": "BackpackChange",
        "Removed": [
            {"Name": "healthpack", "OwnerID": 0, "Count": 2, "Type": "Consumable"},
        ],
    }
    inventory.handle(engine, "BackpackChange", event, [])
    assert "healthpack" not in engine.state.backpack_items


def test_backpackchange_removed_partial_keeps_remainder(engine):
    engine.state.backpack_items = {"healthpack": 5}
    event = {
        "event": "BackpackChange",
        "Removed": [{"Name": "healthpack", "OwnerID": 0, "Count": 2, "Type": "Consumable"}],
    }
    inventory.handle(engine, "BackpackChange", event, [])
    assert engine.state.backpack_items == {"healthpack": 3}


def test_backpackchange_added_and_removed_in_same_event(engine):
    # A single BackpackChange can carry both arrays at once (e.g. crafting
    # something that consumes one material and produces another).
    event = {
        "event": "BackpackChange",
        "Added": [{"Name": "rdx", "Name_Localised": "RDX", "OwnerID": 0, "Count": 1, "Type": "Component"}],
        "Removed": [{"Name": "graphene", "OwnerID": 0, "Count": 1, "Type": "Component"}],
    }
    engine.state.backpack_items = {"graphene": 1}
    inventory.handle(engine, "BackpackChange", event, [])
    assert engine.state.backpack_items == {"rdx": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: all 5 new tests FAIL — `test_backpack_fields_exist_on_state` with `AttributeError` (fields don't exist yet), the `BackpackChange` tests because `inventory.handle()` doesn't recognize that event name yet (returns `False`, and `engine.state.backpack_items` doesn't exist to assert against).

- [ ] **Step 3: Add the new state fields**

Re-read `edc/core/state.py` fresh (it was already edited once in Task 1 — confirm the current post-Task-1 content before editing further). Find the `shiplocker_last_update` line (now the last line of that block, since Task 1 removed `shiplocker_items_loc` right after it) and add the new fields directly after it:

```python
    # Odyssey (on-foot) inventory snapshot (journal-derived)
    shiplocker_items: Dict[str, int] = field(default_factory=dict)        # internal name -> count
    shiplocker_localised: Dict[str, str] = field(default_factory=dict)    # internal name -> display
    shiplocker_last_update: Optional[str] = None                          # journal timestamp

    # Odyssey (on-foot) backpack snapshot -- separate from the ship
    # locker; carried on the commander's person, not stored on the ship.
    backpack_items: Dict[str, int] = field(default_factory=dict)          # internal name -> count
    backpack_localised: Dict[str, str] = field(default_factory=dict)      # internal name -> display
```

- [ ] **Step 4: Add the `BackpackChange` handler**

Re-read `edc/engine/handlers/inventory.py` fresh (it was already edited once in Task 1 — confirm current content). Add this helper function directly after `_adjust_material()` (before `def handle(`):

```python
def _adjust_backpack(engine, rec: Dict[str, Any], delta: int) -> None:
    """
    Apply a +/- delta to a single backpack material's live count, keeping
    the matching localised-name dict in sync -- same shape as
    _adjust_material() above, but backpack_items is one flat dict (no
    per-category split), so there's no category-attr lookup needed.
    """
    nm = rec.get("Name")
    if not isinstance(nm, str):
        return
    key = nm.strip().lower()
    if not key:
        return
    nl = rec.get("Name_Localised")
    display = nl.strip() if isinstance(nl, str) and nl.strip() else None

    counts = engine.state.backpack_items
    new_count = counts.get(key, 0) + delta
    if new_count > 0:
        counts[key] = new_count
    else:
        counts.pop(key, None)
    if display:
        engine.state.backpack_localised[key] = display
```

Then add a new branch inside `handle()`, directly after the existing `elif name == "MaterialTrade":` block (before `elif name == "EngineerCraft":`):

```python
    elif name == "BackpackChange":
        for item in (event.get("Added") or []):
            if isinstance(item, dict):
                _adjust_backpack(engine, item, +int(item.get("Count") or 0))
        for item in (event.get("Removed") or []):
            if isinstance(item, dict):
                _adjust_backpack(engine, item, -int(item.get("Count") or 0))
        return True
```

- [ ] **Step 5: Run tests to verify they pass so far**

Run: `python -m pytest tests/test_odyssey_inventory.py -v`
Expected: `test_backpack_fields_exist_on_state` and all 4 `BackpackChange` tests PASS.

- [ ] **Step 6: Add `_load_backpack_inventory()` and wire it**

Re-read `edc/ui/main_window.py` fresh (already edited once in Task 2 — confirm current content, including the new `_load_shiplocker_inventory()` method and its wiring). Add this new method directly after `_load_shiplocker_inventory()`:

```python
    def _load_backpack_inventory(self):
        """
        Reads Backpack.json -- always re-read on every "Backpack" event
        regardless of whether that particular event happens to carry the
        category arrays inline, since Backpack's inline-vs-bare behavior
        wasn't fully pinned down during investigation and a cheap file
        read is correct either way (same robustness reasoning as
        _load_cargo_inventory() and _load_shiplocker_inventory() above).
        Same four-category merge as ShipLocker.
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        path = Path(journal_dir) / "Backpack.json"
        try:
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read Backpack.json")
            return

        if not isinstance(data, dict):
            return

        counts: dict = {}
        loc: dict = {}
        for category in ("Items", "Components", "Data", "Consumables"):
            c, l = self.engine._parse_shiplocker_items(data.get(category))
            counts.update(c)
            loc.update(l)
        self.state.backpack_items = counts
        self.state.backpack_localised = loc
```

Then find the `if name == "ShipLocker":` block added in Task 2 and add a new `Backpack` block directly after it:

```python
        if name == "ShipLocker":
            # Same journal quirk as Cargo above, and the same fix.
            self._load_shiplocker_inventory()
            self._refresh_engineering()

        if name == "Backpack":
            self._load_backpack_inventory()
            self._refresh_engineering()

        if name == "EngineerProgress":
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 8: Byte-compile check**

Run: `python -m py_compile edc/core/state.py edc/engine/handlers/inventory.py edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 9: Commit**

```bash
git add edc/core/state.py edc/engine/handlers/inventory.py edc/ui/main_window.py tests/test_odyssey_inventory.py
git commit -m "feat: track Backpack inventory via Backpack.json re-reads and BackpackChange deltas"
```

---

### Task 4: Combine both pools in the Odyssey Engineering tab

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`

**Interfaces:**
- Consumes: `state.shiplocker_items`/`shiplocker_localised` (unchanged names, now correctly populated — Tasks 1-2), `state.backpack_items`/`backpack_localised` (Task 3).
- Produces: nothing consumed elsewhere — final task in this plan.

- [ ] **Step 1: Combine held counts from both pools**

Re-read `edc/ui/panels/engineering_panel.py` fresh (flagged frequently-stale; this exact class was modified by earlier plans this session — confirm current line numbers, they were ~900-911 when last read). Current code:

```python
    def _held_count(self, symbol: str) -> int:
        if self._state is None:
            return 0
        src = getattr(self._state, "shiplocker_items", None) or {}
        return int(src.get(symbol.lower(), 0))

    def _material_name(self, symbol: str) -> str:
        loc = getattr(self._state, "shiplocker_localised", None) or {} if self._state else {}
        localised = loc.get(symbol.lower())
        if localised:
            return localised
        return self._table.material_display_name(symbol) or symbol
```

Replace with (sums both pools for the count; checks ShipLocker's localised name first, then Backpack's, before falling through to the static table):

```python
    def _held_count(self, symbol: str) -> int:
        if self._state is None:
            return 0
        key = symbol.lower()
        shiplocker = getattr(self._state, "shiplocker_items", None) or {}
        backpack = getattr(self._state, "backpack_items", None) or {}
        return int(shiplocker.get(key, 0)) + int(backpack.get(key, 0))

    def _material_name(self, symbol: str) -> str:
        key = symbol.lower()
        shiplocker_loc = getattr(self._state, "shiplocker_localised", None) or {} if self._state else {}
        localised = shiplocker_loc.get(key)
        if localised:
            return localised
        backpack_loc = getattr(self._state, "backpack_localised", None) or {} if self._state else {}
        localised = backpack_loc.get(key)
        if localised:
            return localised
        return self._table.material_display_name(symbol) or symbol
```

- [ ] **Step 2: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass (this task adds no new automated tests — pure consumption of already-tested state fields, verified visually/live per this tab's established convention).

- [ ] **Step 4: Headless verification**

Write a scratch script (in this project's scratchpad, not committed) that builds a real `_OdysseyEngineeringTab`-independent check: construct a `GameState`, set `shiplocker_items = {"rdx": 3}` and `backpack_items = {"rdx": 2}`, and confirm a `_OdysseyEngineeringTab` instance's `_held_count("rdx")` returns `5` (the combined total). Also set `shiplocker_localised = {}` and `backpack_localised = {"rdx": "RDX"}` and confirm `_material_name("rdx")` returns `"RDX"` (falls through to the Backpack pool when ShipLocker's is empty). Report the actual output.

- [ ] **Step 5: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: combine ShipLocker and Backpack pools for Odyssey held-material counts and names"
```
