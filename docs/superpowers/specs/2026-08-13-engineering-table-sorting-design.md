# Engineering Panel Table Sorting — Design

## Context

The Engineering tab (`edc/ui/panels/engineering_panel.py`, Ships and Suits &
Weapons sub-tabs) has no way to sort any of its tables — Blueprint/Odyssey
Wishlist, Materials Required, Available From (engineers), Sold By Carriers,
Material Trader Suggestions. User wants click-to-sort column headers across
all of them.

## Research

Two things confirmed by reading the current code, not assumed:

1. **A real correctness risk in the Wishlist tables specifically.** Every
   detail view (Materials Required, Available From, Sold By Carriers) reads
   the currently-selected wishlist item via
   `row = self._wl_table.currentRow(); entry = self._wishlist[row]` — a
   *positional* lookup into the Python list backing the table. 12 call
   sites do this across both tab classes (delete, all three detail-refresh
   methods, `_missing_count`). Enabling `setSortingEnabled(True)` naively
   makes Qt reorder the table's visual rows on a header click without
   reordering `self._wishlist` — so after any sort, "the row currently
   under your cursor" would silently map to the wrong list entry. The
   detail tables (Materials Required, Available From, Sold By Carriers,
   Trader Suggestions) have no such risk — nothing indexes back into a
   backing list from them, they're pure display.
2. **Plain `QTableWidgetItem` sorts alphabetically, not numerically.** This
   codebase already solved this exact problem once, in
   `player_faction_panel.py`'s `_NumericTableWidgetItem` (a `QTableWidgetItem`
   subclass overriding `__lt__` to compare a stored `_sort_value` instead of
   the displayed text — "42.0%" would otherwise sort before "9.0%"). Without
   it, this feature's numeric columns (Grade, Held, Required, Dist (ly),
   Price, Stock, Age) would sort as text and make the feature actively
   misleading rather than just absent. Following this project's own
   established convention of small per-file duplication over cross-file
   sharing for compact UI helpers (e.g. the two tabs' own near-identical
   `_refresh_engineer_table()` methods), a local copy of the same class is
   added to `engineering_panel.py` rather than importing across UI files.

Column audit (which columns in which tables need `_NumericTableWidgetItem`,
confirmed by reading each table's current header list and population code):

| Table | Tab(s) | Numeric columns |
|---|---|---|
| Wishlist | Ships | Grade |
| Wishlist | Odyssey | *(none — "Item" already embeds "(grade N)" in its label text, no separate Grade column)* |
| Materials Required | Both | Held, Required |
| Available From | Both | Dist (ly) |
| Sold By Carriers | Both | Dist (ly), Price, Stock, Age |
| Material Trader Suggestions | Ships only | *(none — both columns are text)* |

`Age` (e.g. "1d / 2d", built this session from `last_updated`/`last_visited`)
needs a numeric sort value too, even though it isn't a plain number — the
underlying age-in-seconds (already computed internally by the existing
`_format_age()` helper before being formatted into the display string) is
the natural sort key; the displayed text stays exactly as-is.

## Design

### 1. `_NumericTableWidgetItem` (new, local to `engineering_panel.py`)

Direct copy of `player_faction_panel.py`'s class (same `__lt__` override
pattern), placed near the top of the file alongside `_make_table()`.

### 2. Sorting enabled everywhere

`_make_table()` gains `t.setSortingEnabled(True)` — this one-line change
in the shared helper turns on click-to-sort for every table built through
it, in both tabs, with no other code needed for the detail tables (pure
display, safe as-is).

### 3. Numeric columns use `_NumericTableWidgetItem`

Every numeric-column cell construction (per the audit table above) changes
from `QTableWidgetItem(str(value))` to
`_NumericTableWidgetItem(str(value), value)` (or the appropriate
seconds-based sort value for Age). Non-numeric columns are untouched.

### 4. Wishlist selection becomes sort-safe

The 12 `self._wl_table.currentRow()` → `self._wishlist[row]` call sites
(both tab classes) change to:

- **Row build**: when populating `_wl_table`, the row's first-column
  `QTableWidgetItem` gets `.setData(Qt.ItemDataRole.UserRole, entry)`
  attaching the actual wishlist dict to that row, independent of position.
- **Row read** (the 10 read sites: 3 detail-refresh methods × up-to-2 call
  patterns each, plus `_missing_count`'s selection-driven callers):
  `entry = self._wl_table.currentItem().data(Qt.ItemDataRole.UserRole)`
  (with the existing `if row < 0: return`-style empty-selection guard kept,
  now checking `self._wl_table.currentItem() is None` instead of
  `row < 0`).
- **Delete** (`_remove_selected()`, both tabs): reads the entry the same
  UserRole way, then removes it from `self._wishlist` by value
  (`self._wishlist.remove(entry)`) instead of by index
  (`del self._wishlist[row]`) — safe because wishlist entries are already
  required to be unique at add-time (both tabs already reject a duplicate
  `entry` before appending, confirmed in the existing `_add_to_wishlist()`
  methods), so value-based removal is unambiguous.

No change to `_wishlist`'s own storage (still a plain Python list, still
saved/loaded the same way) — only how the currently-selected entry is
*found*, which becomes independent of visual row order.

## Testing

Pure UI/Qt-widget behavior with no synthetic-testable business logic
(matches this file's existing convention — this session's other Engineering
panel work was verified live, not unit-tested). Verified live: click a
numeric column header on each affected table, confirm ascending/descending
toggles and sorts numerically (not alphabetically); on the Wishlist tables
specifically, sort by a column, select a row, confirm Materials
Required/Available From/Sold By Carriers show the correct entry's data (not
the entry that used to occupy that visual row before sorting); delete a
row after sorting, confirm the correct entry is removed.
