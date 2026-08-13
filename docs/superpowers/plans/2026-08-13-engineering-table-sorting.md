# Engineering Panel Table Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every table in the Engineering panel's Ships and Suits & Weapons tabs click-to-sort by column, with numeric columns sorting numerically (not alphabetically), without breaking the Wishlist tables' selection-driven detail views.

**Architecture:** A local `_NumericTableWidgetItem` class (mirroring the existing one in `player_faction_panel.py`), `setSortingEnabled(True)` added once in the shared `_make_table()` helper (with every populate-loop guarded against a known sort-during-populate corruption gotcha), numeric-column cell construction switched to the new class, and the Wishlist tables' 8 `currentRow()`-into-list-index lookups (2 of which are deletes, the other 6 are read-only entry lookups) switched to `Qt.ItemDataRole.UserRole`-based lookups so sorting never desyncs the visual row from the underlying `self._wishlist` entry.

**Tech Stack:** Python, PyQt6.

## Global Constraints

- Single file: `edc/ui/panels/engineering_panel.py`. No other files change.
- The detail tables (Materials Required, Available From, Sold By Carriers, Material Trader Suggestions) need ONLY `setSortingEnabled(True)` (via the shared helper) plus numeric-item treatment where applicable — they have no backing-list-index dependency, so no other changes.
- The Wishlist tables (`_wl_table` in both `_ShipEngineeringTab` and `_OdysseyEngineeringTab`) are the only ones where selection tracking must change from positional (`currentRow()` → `self._wishlist[row]`) to identity-based (`currentItem().data(Qt.ItemDataRole.UserRole)`), because their `self._wishlist` Python list does not reorder when the table is visually sorted.
- Deleting a wishlist entry (`_remove_selected()` in both classes) switches from `del self._wishlist[row]` (positional) to `self._wishlist.remove(entry)` (by value) — safe because both classes already reject duplicate entries at add-time (confirmed: `_ShipEngineeringTab._add_to_wishlist()` and `_OdysseyEngineeringTab._add_to_wishlist()` both check `if any(e == entry ...): return` before appending), so no two wishlist entries can ever be equal.
- No new automated tests — this is pure Qt widget behavior with no synthetic-testable business logic, matching this file's existing convention (every other Engineering panel change this session was verified live, not unit-tested).

---

## File Structure

- **Modify:** `edc/ui/panels/engineering_panel.py` only.

---

### Task 1: Sortable columns with sort-safe wishlist selection

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`

**Interfaces:**
- Consumes: nothing new
- Produces: nothing consumed by other tasks — this is the only task

- [ ] **Step 1: Add `_NumericTableWidgetItem`**

Re-read `edc/ui/panels/engineering_panel.py` fresh — this project's CLAUDE.md flags UI panel files as frequently stale, and the exact line numbers below are from this plan's own research pass, not guaranteed current. Directly after the `_make_table()` function (currently ends with `return t`), add:

```python
class _NumericTableWidgetItem(QTableWidgetItem):
    """Sorts by an actual numeric value instead of the displayed string
    (plain QTableWidgetItem sorting would put "42.0" before "9.0")."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, _NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)
```

- [ ] **Step 2: Enable sorting in the shared table helper**

In `_make_table()`, add one line directly after `t.setAlternatingRowColors(True)`:

```python
    t.setSortingEnabled(True)
```

- [ ] **Step 3: Guard every table-populate loop against sort-during-populate corruption**

**This is the step most likely to be skipped by accident — it is not optional.** A well-known PyQt/Qt gotcha: when `setSortingEnabled(True)` is on, calling `setItem()` in a loop to repopulate a table (after `setRowCount(...)`) can trigger a re-sort after each individual `setItem()` call if the table is already sorted from a previous click — rows shift mid-loop, and items end up written to the wrong (post-resort) row, corrupting the display. The standard, minimal fix: temporarily disable sorting for the duration of each populate loop.

Every method in this file that calls `<table>.setRowCount(...)` followed by a loop of `<table>.setItem(...)` calls needs `<table>.setSortingEnabled(False)` immediately before the loop and `<table>.setSortingEnabled(True)` immediately after it ends (before any trailing code in the method that isn't part of the loop, e.g. before the `staleness_note`/`_carrier_note.setText(...)` lines in the carrier-table methods). This applies to ALL of the following (both classes unless noted):

- `_refresh_wishlist_table()` (`self._wl_table`) — both classes
- `_refresh_detail_table()` (`self._detail_table`) — both classes
- `_refresh_engineer_table()` (`self._engineer_table`) — both classes
- `_refresh_carrier_table()` (`self._carrier_table`) — both classes
- `_refresh_trade_suggestions()` (`self._trade_table`) — Ships tab only (no Odyssey equivalent)

For each, wrap exactly the `setRowCount(...)` + `for ...: ... setItem(...)` portion. Example shape (using `_ShipEngineeringTab._refresh_wishlist_table()` as illustration — apply the same wrapping pattern to every method listed above, adapting to that method's own loop):

```python
    def _refresh_wishlist_table(self):
        self._wl_table.setSortingEnabled(False)
        self._wl_table.setRowCount(len(self._wishlist))
        for r, entry in enumerate(self._wishlist):
            ... # existing loop body, unchanged
            self._wl_table.setItem(r, 0, name_item)
            self._wl_table.setItem(r, 1, grade_item)
            self._wl_table.setItem(r, 2, status_item)
        self._wl_table.setSortingEnabled(True)
        self._refresh_detail_table()
```

(Note `self._refresh_detail_table()` stays AFTER re-enabling sorting, not inside the guarded block — only the `setItem` loop itself needs guarding.) Apply this same before/after wrapping to each of the 9 methods listed above, using each method's own existing table variable and loop structure — do not otherwise alter any method's logic in this step.

- [ ] **Step 4: Make `_format_age()` return a sort value alongside the display text**

Change `_format_age()`'s signature and body from:

```python
def _format_age(last_updated: str, last_visited: str) -> str:
    """Compact 'listing age / carrier-location age' for the carrier
    table's Age column -- last_updated is when this material listing was
    last seen on EDDN, last_visited is when we last had a Docked sighting
    of the carrier itself (it may have moved since)."""
    listed, _ = relative_time(last_updated)
    visited, _ = relative_time(last_visited)
    return f"{listed.replace(' ago', '')} / {visited.replace(' ago', '')}"
```

to:

```python
def _format_age(last_updated: str, last_visited: str) -> tuple[str, float]:
    """Compact 'listing age / carrier-location age' for the carrier
    table's Age column -- last_updated is when this material listing was
    last seen on EDDN, last_visited is when we last had a Docked sighting
    of the carrier itself (it may have moved since). Returns (display_text,
    sort_value) -- sort_value is the older (larger) of the two ages in
    seconds, since that's the single number that best represents "how
    stale is this row overall" for column sorting."""
    listed, listed_secs = relative_time(last_updated)
    visited, visited_secs = relative_time(last_visited)
    text = f"{listed.replace(' ago', '')} / {visited.replace(' ago', '')}"
    return text, max(listed_secs, visited_secs)
```

- [ ] **Step 5: Switch numeric-column cell construction to `_NumericTableWidgetItem`**

In `_ShipEngineeringTab._refresh_wishlist_table()`, change:

```python
            grade_item = QTableWidgetItem(str(grade))
```

to:

```python
            grade_item = _NumericTableWidgetItem(str(grade), grade)
```

In `_ShipEngineeringTab._refresh_detail_table()`, change:

```python
            held_item = QTableWidgetItem(str(held))
            req_item = QTableWidgetItem(str(qty))
```

to:

```python
            held_item = _NumericTableWidgetItem(str(held), held)
            req_item = _NumericTableWidgetItem(str(qty), qty)
```

In `_ShipEngineeringTab._refresh_engineer_table()`, change:

```python
            dist_item = QTableWidgetItem(f"{dist:.1f}" if dist is not None else "—")
```

to:

```python
            dist_item = _NumericTableWidgetItem(
                f"{dist:.1f}" if dist is not None else "—", dist if dist is not None else -1.0
            )
```

In `_ShipEngineeringTab._refresh_carrier_table()`, change:

```python
            dist_item = QTableWidgetItem(f"{listing['distance_ly']:.1f}")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price = listing.get("price")
            price_item = QTableWidgetItem(f"{price:,}" if isinstance(price, int) else "—")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock = listing.get("stock")
            stock_item = QTableWidgetItem(str(stock) if isinstance(stock, int) else "—")
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            age_item = QTableWidgetItem(_format_age(listing.get("last_updated"), listing.get("last_visited")))
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
```

to:

```python
            dist_item = _NumericTableWidgetItem(f"{listing['distance_ly']:.1f}", listing['distance_ly'])
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price = listing.get("price")
            price_item = _NumericTableWidgetItem(
                f"{price:,}" if isinstance(price, int) else "—", price if isinstance(price, int) else -1
            )
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock = listing.get("stock")
            stock_item = _NumericTableWidgetItem(
                str(stock) if isinstance(stock, int) else "—", stock if isinstance(stock, int) else -1
            )
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            age_text, age_sort = _format_age(listing.get("last_updated"), listing.get("last_visited"))
            age_item = _NumericTableWidgetItem(age_text, age_sort)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
```

Repeat the identical four changes in `_OdysseyEngineeringTab`'s equivalent methods:
- `_refresh_wishlist_table()` has no Grade column (the "Item" column already embeds "(grade N)" in its label text) — no change needed there.
- `_refresh_detail_table()`: change `held_item`/`req_item` construction the same way as the Ship tab's version above.
- `_refresh_engineer_table()`: change `dist_item` construction the same way.
- `_refresh_carrier_table()`: change `dist_item`/`price_item`/`stock_item`/`age_item` construction the same way (identical code, this method is near-duplicated between the two classes already).

- [ ] **Step 6: Attach the wishlist entry to each row as item data (both classes)**

In `_ShipEngineeringTab._refresh_wishlist_table()`, directly after building `name_item = QTableWidgetItem(label)`, add:

```python
            name_item.setData(Qt.ItemDataRole.UserRole, entry)
```

In `_OdysseyEngineeringTab._refresh_wishlist_table()`, directly after building `name_item = QTableWidgetItem(self._display_name(entry))`, add the identical line:

```python
            name_item.setData(Qt.ItemDataRole.UserRole, entry)
```

- [ ] **Step 7: Replace every positional wishlist-selection read with a UserRole read (both classes)**

Add a small shared helper to each class (placed near the top of each class's method list, e.g. directly before `_remove_selected()`), since the two classes don't share a common base class to put it on once:

```python
    def _selected_wishlist_entry(self) -> Optional[Dict[str, Any]]:
        item = self._wl_table.currentItem()
        if item is None:
            return None
        # Any column's item on the selected row carries the same UserRole
        # data (only column 0 is explicitly set) -- currentItem() can
        # return any column depending on which cell was clicked, so look
        # up column 0 of that row explicitly rather than assuming.
        row = item.row()
        col0 = self._wl_table.item(row, 0)
        return col0.data(Qt.ItemDataRole.UserRole) if col0 else None
```

Add this identical method to BOTH `_ShipEngineeringTab` and `_OdysseyEngineeringTab`.

Then replace each of the following patterns. In `_ShipEngineeringTab`:

`_remove_selected()` — change:
```python
    def _remove_selected(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            return
        del self._wishlist[row]
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()
```
to:
```python
    def _remove_selected(self):
        entry = self._selected_wishlist_entry()
        if entry is None or entry not in self._wishlist:
            return
        self._wishlist.remove(entry)
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()
```

`_refresh_detail_table()` — change:
```python
    def _refresh_detail_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
        entry = self._wishlist[row]
```
to:
```python
    def _refresh_detail_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
```
(the rest of the method body is unchanged — it already uses the local `entry` variable from this point on).

`_refresh_engineer_table()` — change:
```python
    def _refresh_engineer_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._engineer_table.setRowCount(0)
            return
        entry = self._wishlist[row]
```
to:
```python
    def _refresh_engineer_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._engineer_table.setRowCount(0)
            return
```

`_refresh_carrier_table()` — change:
```python
    def _refresh_carrier_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("")
            return
        entry = self._wishlist[row]
```
to:
```python
    def _refresh_carrier_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("")
            return
```

Now the identical four changes in `_OdysseyEngineeringTab`, with one difference: its `_refresh_engineer_table()` takes an optional `entry` parameter (called with an explicit `entry` from `_refresh_detail_table()`, and with no argument from at least one other call site) — only its internal `if entry is None:` fallback branch changes, the parameter itself stays:

`_remove_selected()` — same change as the Ship tab's version above.

`_refresh_detail_table()` — change:
```python
    def _refresh_detail_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
        entry = self._wishlist[row]
```
to:
```python
    def _refresh_detail_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
```

`_refresh_engineer_table(self, entry: Optional[Dict[str, Any]] = None)` — change only the internal fallback:
```python
        if entry is None:
            row = self._wl_table.currentRow()
            if row < 0 or row >= len(self._wishlist):
                self._engineer_table.setRowCount(0)
                self._engineer_note.setText("")
                return
            entry = self._wishlist[row]
```
to:
```python
        if entry is None:
            entry = self._selected_wishlist_entry()
            if entry is None:
                self._engineer_table.setRowCount(0)
                self._engineer_note.setText("")
                return
```

`_refresh_carrier_table()` — same change as the Ship tab's version above.

- [ ] **Step 8: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 9: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests still pass (this task adds no new automated tests).

- [ ] **Step 10: Visual + live verification**

Launch the app, open the Engineering tab, on BOTH the Ships and Suits & Weapons sub-tabs:
- Add at least 2-3 items to the Wishlist so sorting has something to do.
- Click each table's column headers (Wishlist, Materials Required, Available From, Sold By Carriers where applicable) — confirm ascending/descending sort toggles on click, and numeric columns (Grade, Held, Required, Dist (ly), Price, Stock, Age) sort by actual value, not alphabetically (e.g. "9" sorts before "10", not after).
- On the Wishlist table specifically: click a column header to sort (changing visual row order), then click a row. Confirm Materials Required / Available From / Sold By Carriers all show data for the entry you actually clicked, not whatever entry used to occupy that row position before sorting.
- Sort the Wishlist table, select a row, delete it (remove button). Confirm the entry you selected is the one actually removed, and the wishlist file on disk reflects the correct remaining entries (re-open Settings or restart to confirm persistence if easy to check).
- Confirm the Material Trader Suggestions table (Ships tab only, text-only columns) still sorts alphabetically without error — no numeric-item changes were needed there, just confirm `setSortingEnabled` didn't break it.

- [ ] **Step 11: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: add click-to-sort columns to Engineering panel tables"
```
