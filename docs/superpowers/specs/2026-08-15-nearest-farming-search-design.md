# Nearest Farming Opportunity Search — Design

## Context

The Intel tab already shows farming-guide matches for the CURRENT system
only (both static named-site matches via `FarmingLocations.get_for_system()`
and live-BGS-state matches via `_get_system_opportunities()`/
`_entry_matches_system()`, both fixed for precision earlier this session).
There is no way to search for the nearest known farming opportunity for
a specific material across OTHER systems the player isn't currently in.

User wants: a search, from the player's current position, for the
closest place to farm a given material — combining both static named
sites (fixed coordinates, e.g. Arai's Mine) and live BGS-state-driven
opportunities in nearby systems (e.g. a system currently in Outbreak,
which makes Pharmaceutical Isolators farmable there via HGE) — sorted
nearest-first with no distance cutoff (a filter narrows results by
material name, not by how far away they are).

User confirmed scope via clarifying questions:
- No distance cutoff — sort nearest-first, show everything that matches.
- Both static sites and live BGS-state matches, combined into one list.
- Filter by material name (a text box), not just a raw unfiltered list.
- New card on the existing Intel tab (not a new tab).

## Data sources

**Static sites**: `FarmingLocations._records` entries carrying a `system`
field (Arai's Mine, Dav's Hope, Guardian sites, Jameson's Crashed Cobra,
etc.) — fixed, no live-state dependency. Distance via `system_coords`
lookup by system name.

**Live BGS-state matches**: `faction_snapshots` (system_address,
government, faction_state, active_states JSON, is_controlling,
data_timestamp) — the same table `Repository.get_odyssey_farming_candidates()`
already searches for the existing Odyssey Farming Candidates card, fed by
the player's own journal, EDSM lookups, and galaxy-wide EDDN traffic.
Confirmed small scale: 850 distinct tracked systems, 35,237 rows total —
a Python-side fetch-then-sort is trivial here, no risk of the SQL
bound-parameter issue fixed earlier this session (that was specific to
building a per-row `IN (...)` clause; this is a plain filtered `SELECT`
with `ORDER BY` done in Python after fetch).

**Deliberate scope choice**: unlike the current-system live card (which
unions ANY faction present, `_get_system_opportunities`), this search
uses **`is_controlling = 1` only** — tighter, matches the precedent
already set by `get_odyssey_farming_candidates()`, and avoids surfacing a
system as a match just because its 4th-place faction happens to be in
the right state. This is a new, separate code path — it does not change
the current-system card's existing (looser) behavior.

## Architecture: persistence fetches, UI matches

**Correction caught before writing the plan:** an earlier draft of this
section put the guide-matching logic (which needs `_entry_matches_system()`/
`_state_text_to_tags()`) inside a new `Repository` method. That violates
an explicit, existing constraint in this codebase — `persistence/repository.py`'s
own `_parse_states()` docstring states outright: *"persistence must not
depend on the UI layer."* `_entry_matches_system`/`_state_text_to_tags`
live in `edc/ui/panels/intel_panel.py` (UI layer) by design. Splitting
correctly:

**New repository method (data-fetch only, no guide-matching logic):**

`Repository.get_controlling_faction_snapshots_with_coords() -> list[dict]`

One query: `faction_snapshots` (`is_controlling = 1`, most recent
`snapshot_date` per system — same latest-per-system subquery shape
`get_odyssey_farming_candidates()` already uses) `JOIN systems` for
`system_name`, `JOIN system_coords` for `x`/`y`/`z`. Returns
`{"system_name", "government", "allegiance", "faction_state",
"active_states", "x", "y", "z"}` per row — raw data, no interpretation.
(`faction_snapshots` has no security/economy columns — those are
system-level, not faction-level, and aren't tracked at this
granularity. Not a gap: none of the guide's current `state_tags` values
need them.)

Static-site coordinates reuse the existing
`Repository.get_system_coords_for_names(names: list[str]) -> dict`
(`persistence/repository.py:817-828`) — no new method needed for that
half.

**UI-layer orchestration (in `edc/ui/panels/intel_panel.py`):**

A new module-level `_tags_from_faction_snapshot_row(row: dict) -> set`,
parallel to `_get_system_opportunities(state)` but reading a DB row's
fields (`government`, `allegiance`, `faction_state`, `active_states` —
parsed the same way `persistence/repository.py`'s `_parse_states()`
already parses this exact column shape elsewhere) instead of a live
`state` object. Produces the same tag vocabulary
`_get_system_opportunities` produces (minus the security/economy-derived
tags, which this data source can't populate).

Per this file's established convention (every existing piece of
matching logic — `_get_system_opportunities`, `_entry_matches_system`,
`_state_text_to_tags` — is a testable module-level function, specifically
because no `QApplication`/`conftest.py` exists anywhere in this repo's
test suite and none of those functions needed one), the merge/filter/
sort step is ALSO a pure module-level function, not an `IntelPanel`
method:

`_build_nearby_farming_results(static_matches: list[dict], live_rows: list[dict], guide_records: list[dict], opportunities_per_row: ..., material_filter: str, ref_x, ref_y, ref_z) -> list[dict]`

(exact parameter shape finalized during planning — the point is it takes
already-fetched data in, returns the final sorted/capped list out, no
`self`, no DB access, fully unit-testable.)

`IntelPanel` gains one thin orchestration method,
`_search_nearby_farming(self, material_filter: str) -> list[dict]`, whose
only job is: fetch (`self._repo.get_controlling_faction_snapshots_with_coords()`,
`self._repo.get_system_coords_for_names(...)` for static sites), then
call the pure function above and return its result. This method itself
has no independent logic worth unit-testing beyond "does it call the
right things" — covered by live verification, same as this file's other
`refresh()`-adjacent wiring.

1. **Static sites**: entries in `self._farming_locations._records` with
   a `system` field, coordinates via
   `self._repo.get_system_coords_for_names(...)`, one result row per
   material (`key_materials` entries, or `examples[]` entries for the
   HGE-shaped record).
2. **Live BGS-state matches**: `self._repo.get_controlling_faction_snapshots_with_coords()`,
   tags per row via `_tags_from_faction_snapshot_row()`, matched via
   `_entry_matches_system(record, row_tags)` for every guide record
   carrying `state_tags`/`examples` — non-empty means a match; for
   `examples`-bearing records, only the matched example(s) become
   result rows (same precision principle as the current-system fix).
3. If `material_filter` is given (case-insensitive substring match on
   material name), apply it before computing distance for rows about to
   be discarded.
4. Merge both lists, sort by `distance_ly` ascending, truncate to a
   fixed display cap (50 — a UI-sanity limit, not the user's "no
   cutoff" distance decision, which governs ranking/visibility, not
   count).

This means `IntelPanel` needs a `self._repo` reference for the first
time — every other card on this panel is fed passively via `refresh()`
args and holds no repo/main_window reference at all. `MiningPanel`
already establishes the precedent for a panel holding `self._repo` for
exactly this reason (interactive, on-demand search), so this isn't a
new pattern — `IntelPanel.__init__(self, repo, parent=None)`.

Each result row: `{"material": str, "site_name": str, "system_name": str,
"distance_ly": float, "source": "static"|"live", "state": str|None}`
(`state` populated only for live matches, e.g. `"Outbreak"` — the UI
shows it as the reason this result matched).

## UI

New card on the Intel tab, `edc/ui/panels/intel_panel.py`, placed after
the existing "FARMING GUIDE — ALL CATEGORIES" card: header "NEAREST
FARMING OPPORTUNITIES", a `QLineEdit` filter (placeholder "Filter by
material..."), and a `QTableWidget` (Material | Site/System | Distance
| Source) — matching this file's existing table-less, label-based
rendering convention is NOT followed here on purpose: every other card
on this panel is a `QLabel` with rich text, but a sortable, scannable
result list is exactly what `QTableWidget` is for elsewhere in this app
(Market, Mining, Trade Routes) — follow THAT established convention
instead, including click-to-copy on the system-name cell (`QApplication.clipboard().setText(...)`,
same pattern already used in `market_panel.py`/`mining_panel.py`/etc.).

The filter box re-triggers the search on text change (debounced or not —
given the underlying query is fast at this data scale, no debounce
needed, matches how `MaterialsPanel`'s filter box already behaves
elsewhere in this app).

## Testing

- `Repository.get_controlling_faction_snapshots_with_coords()`:
  real-SQLite tests (tmp_path, matching this repo's established
  fixture pattern) — a controlling faction's row is returned with
  correct coords; a non-controlling faction's row is excluded (confirms
  the `is_controlling`-only scope); only the most recent `snapshot_date`
  per system is returned when multiple exist; a system with no
  `system_coords` row is excluded (can't compute distance without it).
- `_tags_from_faction_snapshot_row()`: pure-function tests mirroring
  `_get_system_opportunities()`'s existing test style (module-level,
  no Qt), confirming it derives the same tag vocabulary from a DB-row
  shape.
- `_build_nearby_farming_results()`: pure-function tests (no Qt) —
  static site distance/material rows produced correctly; live-match
  rows produced correctly with the right `state` value; material filter
  narrows both sources; results sorted nearest-first across both
  sources combined; display cap respected; a guide record with no
  match in either source produces nothing.
- `IntelPanel._search_nearby_farming()` (the thin orchestration
  wrapper) and the QTableWidget rendering: no automated test, matches
  this codebase's established convention for panel-level Qt wiring —
  verified live.

## Out of scope

- The 4 findings from the earlier broad sweep (HGE materials invisible
  to the engineering-shortage alert; "Civil Unrest" TTS brief can't
  fire; Civil Unrest/Infrastructure Failure badges render gray; the
  duplicate wrong-domain HGE guide entry) — queued as a separate
  follow-up pass, not part of this feature.
- Changing the current-system live card's any-faction matching to
  controlling-only — that card is unchanged; this is a new, separate,
  intentionally-tighter code path.
- A distance cutoff/radius setting — explicitly rejected, no cutoff.
