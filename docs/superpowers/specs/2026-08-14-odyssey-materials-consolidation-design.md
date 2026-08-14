# Odyssey → Materials Tab Consolidation — Design

## Context

`edc/ui/panels/inventory_panel.py` has two near-identical panels: `MaterialsPanel`
(Raw/Manufactured/Encoded ship-engineering materials, via a `QComboBox`
category dropdown) and `ShiplockerPanel` (Odyssey on-foot inventory, a
separate top-level sidebar tab). Both instantiated in `main_window.py` as
separate stack widgets.

`ShiplockerPanel` only reads `state.shiplocker_items` — it never included
`state.backpack_items` (added later this session for `BackpackChange`
tracking), so it under-counts vs. the Engineering tab, which already sums
both (`engineering_panel.py:_held_count`/`_material_name`).

User confirmed a standalone Odyssey tab isn't needed — it belongs as a 4th
category in the Materials tab, same as any other inventory grouping.

## Changes

### `edc/ui/panels/inventory_panel.py`

- Delete `ShiplockerPanel` class entirely (lines 18-167).
- `MaterialsPanel.__init__`: `inv_kind.addItems([...])` gains `"Odyssey"` as
  a 4th item: `["Raw", "Manufactured", "Encoded", "Odyssey"]`.
- `MaterialsPanel.refresh`: the `if kind == "Raw": ... elif ...` chain
  selecting `src` gains:
  ```python
  elif kind == "Odyssey":
      sl = getattr(state, "shiplocker_items", {}) or {}
      bp = getattr(state, "backpack_items", {}) or {}
      src = {}
      for k, v in sl.items():
          src[k] = src.get(k, 0) + v
      for k, v in bp.items():
          src[k] = src.get(k, 0) + v
  ```
  (mirrors `engineering_panel.py:_held_count`'s shiplocker+backpack sum).
- Localised-name lookup: today `localised = getattr(state,
  "materials_localised", {})` unconditionally. Change to branch on `kind`:
  Odyssey uses `shiplocker_localised` merged with `backpack_localised`
  (shiplocker wins on key collision — mirrors `engineering_panel.py:
  _material_name`'s fallback order):
  ```python
  if kind == "Odyssey":
      localised = dict(getattr(state, "backpack_localised", {}) or {})
      localised.update(getattr(state, "shiplocker_localised", {}) or {})
  else:
      localised = getattr(state, "materials_localised", {}) or {}
  ```
- Timestamp: today `ts = getattr(state, "materials_last_update", None)`
  unconditionally. Change to `ts = getattr(state, "shiplocker_last_update",
  None) if kind == "Odyssey" else getattr(state, "materials_last_update",
  None)` — no separate backpack timestamp exists.
- Empty-state message: today a single fixed string mentioning "Materials"
  journal event. Branch on `kind == "Odyssey"` to show ShiplockerPanel's
  current wording instead ("open the on-foot inventory/locker screen or
  relog so a 'ShipLocker' journal event is emitted").
- Subtype column (`item_catalog.get_subtype_label`) and all table-rendering
  code stay untouched — already generic over item name.

### `edc/ui/main_window.py`

- Remove `self.shiplocker_panel = ShiplockerPanel()` (~line 1280).
- Remove the `(self.shiplocker_panel, "Odyssey")` sidebar-registration
  tuple (~line 1458).
- Remove `self.shiplocker_panel.refresh(self.state, self.item_catalog)`
  (~line 3903).
- Any `_market_tab_row`-style special-cased row-index tracking for the
  Odyssey tab (none found in current code — only "Market" and "Overview"
  are special-cased) — none to remove.

## Out of scope

- No schema/persistence changes — this is UI-only, both source dicts
  (`shiplocker_items`, `backpack_items`) already exist and are already
  correctly populated.
- No change to `engineering_panel.py`'s own combine logic — it stays as
  its own independent read of the same two state dicts.

## Testing

Visual/live confirmation only, per this file's established convention
(no automated tests exist for panel rendering elsewhere in this
codebase). Confirm: Odyssey option shows combined ShipLocker+Backpack
counts matching the Engineering tab's held-count for at least one shared
item; old "Odyssey" sidebar tab is gone; other 3 categories unaffected.
