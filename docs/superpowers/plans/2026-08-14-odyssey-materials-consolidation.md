# Odyssey → Materials Tab Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the standalone Odyssey (`ShiplockerPanel`) sidebar tab into the Materials tab as a 4th category, combining ShipLocker + Backpack counts to match the Engineering tab's held-count logic.

**Architecture:** `MaterialsPanel` (`edc/ui/panels/inventory_panel.py`) gains an "Odyssey" entry in its existing Raw/Manufactured/Encoded category dropdown, with `refresh()` branching to source combined `state.shiplocker_items`+`state.backpack_items` data instead of `state.materials_*`. `ShiplockerPanel` and its `main_window.py` wiring are deleted.

**Tech Stack:** PyQt6 (existing `QComboBox`/`QTableWidget` patterns already in the file).

## Global Constraints

- No schema/persistence changes — `state.shiplocker_items`, `state.backpack_items`, `state.shiplocker_localised`, `state.backpack_localised`, `state.shiplocker_last_update` already exist and are already correctly populated.
- Do not touch `edc/ui/panels/engineering_panel.py` — its `_held_count`/`_material_name` combine logic is the reference pattern to mirror, not to refactor or share via an extracted helper (two call sites, YAGNI).
- No new files.
- No automated tests — verify visually/live per this codebase's established convention for panel rendering.

---

### Task 1: Fold Odyssey into MaterialsPanel, delete ShiplockerPanel

**Files:**
- Modify: `edc/ui/panels/inventory_panel.py`
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `state.shiplocker_items: Dict[str,int]`, `state.backpack_items: Dict[str,int]`, `state.shiplocker_localised: Dict[str,str]`, `state.backpack_localised: Dict[str,str]`, `state.shiplocker_last_update: Optional[str]` (all pre-existing on `GameState`, `edc/core/state.py`).
- Produces: `MaterialsPanel.refresh(state, item_catalog)` now handles `kind == "Odyssey"` alongside the existing three. No other component calls into `MaterialsPanel` differently than before — its public interface (`refresh(state, item_catalog)`) is unchanged.

- [ ] **Step 1: Read the current file fresh**

Read `edc/ui/panels/inventory_panel.py` in full. Confirm the exact current line ranges for `class ShiplockerPanel(QWidget):` and for `class MaterialsPanel(QWidget):`'s `__init__` and `refresh` methods — they may have shifted from a prior session's edits. Do not rely on remembered line numbers.

- [ ] **Step 2: Delete `ShiplockerPanel`**

Delete the entire `class ShiplockerPanel(QWidget):` block, from its `class` line through the blank line(s) immediately before `class MaterialsPanel(QWidget):`.

- [ ] **Step 3: Add "Odyssey" to the category dropdown**

In `MaterialsPanel.__init__`, change:

```python
self.inv_kind.addItems(["Raw", "Manufactured", "Encoded"])
```

to:

```python
self.inv_kind.addItems(["Raw", "Manufactured", "Encoded", "Odyssey"])
```

- [ ] **Step 4: Add the Odyssey source branch in `refresh`**

In `MaterialsPanel.refresh`, the existing chain reads:

```python
src = {}
if kind == "Raw":
    src = getattr(state, "materials_raw", {}) or {}
elif kind == "Manufactured":
    src = getattr(state, "materials_manufactured", {}) or {}
elif kind == "Encoded":
    src = getattr(state, "materials_encoded", {}) or {}
```

Add a fourth branch:

```python
src = {}
if kind == "Raw":
    src = getattr(state, "materials_raw", {}) or {}
elif kind == "Manufactured":
    src = getattr(state, "materials_manufactured", {}) or {}
elif kind == "Encoded":
    src = getattr(state, "materials_encoded", {}) or {}
elif kind == "Odyssey":
    sl = getattr(state, "shiplocker_items", {}) or {}
    bp = getattr(state, "backpack_items", {}) or {}
    src = {}
    for k, v in sl.items():
        src[k] = src.get(k, 0) + v
    for k, v in bp.items():
        src[k] = src.get(k, 0) + v
```

- [ ] **Step 5: Branch the empty-state message on `kind`**

The existing empty-src early return reads:

```python
if not isinstance(src, dict) or not src:
    self.inv_summary.setText(
        "No materials inventory loaded yet.\n"
        "Tip: open the in-game Inventory/Materials screen "
        "or relog so a 'Materials' journal event is emitted."
    )
    self.inv_table.setRowCount(0)
    return
```

Change it to:

```python
if not isinstance(src, dict) or not src:
    if kind == "Odyssey":
        self.inv_summary.setText(
            "No ShipLocker inventory loaded yet.\n"
            "Tip: open the on-foot inventory/locker screen "
            "or relog so a 'ShipLocker' journal event is emitted."
        )
    else:
        self.inv_summary.setText(
            "No materials inventory loaded yet.\n"
            "Tip: open the in-game Inventory/Materials screen "
            "or relog so a 'Materials' journal event is emitted."
        )
    self.inv_table.setRowCount(0)
    return
```

- [ ] **Step 6: Branch the localised-name lookup on `kind`**

The existing line reads:

```python
localised = getattr(state, "materials_localised", {}) or {}
if not isinstance(localised, dict):
    localised = {}
```

Change it to:

```python
if kind == "Odyssey":
    localised = dict(getattr(state, "backpack_localised", {}) or {})
    localised.update(getattr(state, "shiplocker_localised", {}) or {})
else:
    localised = getattr(state, "materials_localised", {}) or {}
if not isinstance(localised, dict):
    localised = {}
```

(`shiplocker_localised` wins on key collision, since `.update()` runs after `backpack_localised` seeds the dict — matches `engineering_panel.py:_material_name`'s fallback order.)

- [ ] **Step 7: Branch the timestamp source on `kind`**

The existing line reads:

```python
ts = getattr(state, "materials_last_update", None)
```

Change it to:

```python
ts = (
    getattr(state, "shiplocker_last_update", None)
    if kind == "Odyssey"
    else getattr(state, "materials_last_update", None)
)
```

- [ ] **Step 8: Leave everything else in `refresh` untouched**

The filter matching, subtype lookup (`item_catalog.get_subtype_label`), row sorting/population, `zero`/`low` counts, catalog text, and final summary string all already operate generically on `src`/`localised`/`ts` — no further changes needed in this method.

- [ ] **Step 9: Remove `ShiplockerPanel` wiring from `main_window.py`**

Read `edc/ui/main_window.py` fresh. Grep for `shiplocker_panel` (case-sensitive) across the whole file to find every reference before editing — do not assume only 3 exist.

Remove:
1. `self.shiplocker_panel = ShiplockerPanel()` (the instantiation line).
2. The `(self.shiplocker_panel,      "Odyssey"),` tuple from the sidebar-registration list (the `for widget, name in [...]` block).
3. `self.shiplocker_panel.refresh(self.state, self.item_catalog)` (the refresh call).

If the grep turns up any additional reference beyond these three (e.g. a special-cased row-index tracker like the existing `_market_tab_row` pattern), remove or adapt it as needed to leave no dangling reference to `shiplocker_panel` or `ShiplockerPanel` anywhere in the file.

- [ ] **Step 10: Static sanity check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/inventory_panel.py').read()); ast.parse(open('edc/ui/main_window.py').read())"`
Expected: no output (both files parse as valid Python).

Run: `grep -rn "ShiplockerPanel\|shiplocker_panel" edc/`
Expected: no matches anywhere in the codebase.

- [ ] **Step 11: Manual verification**

Start the app (`python -m edc.app` or the project's existing launch command — check `README.md`/existing scripts if unsure of the exact invocation). With a save that has ShipLocker and/or Backpack data:

1. Open the Materials tab. Confirm the Category dropdown now shows Raw, Manufactured, Encoded, **Odyssey**.
2. Select Odyssey. Confirm it renders a populated table (Item/Subtype/Count), not the empty-state message (unless the account genuinely has no on-foot inventory).
3. Pick one item name present in both the Odyssey table and the Engineering tab's requirement list (e.g. a common raw material used in a suit/weapon upgrade). Confirm the Odyssey count equals the Engineering tab's displayed held-count for that item.
4. Confirm the sidebar no longer has a standalone "Odyssey" entry.
5. Switch back to Raw/Manufactured/Encoded and confirm each still renders correctly (unaffected by the change).

- [ ] **Step 12: Commit**

```bash
git add edc/ui/panels/inventory_panel.py edc/ui/main_window.py
git commit -m "feat: fold Odyssey inventory into Materials tab as a category"
```
