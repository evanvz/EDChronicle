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

## New repository method

`Repository.search_nearby_farming_opportunities(x, y, z, material_filter=None, limit=50) -> list[dict]`

Two internal steps, merged and sorted once:

1. **Static sites**: iterate `farming_locations._records` (passed in by
   the caller — this method lives in `persistence/repository.py` but
   needs the loaded guide, so it takes `farming_locations` as a
   parameter, mirroring how `intel_panel.py`'s `refresh()` already
   receives it). For each record with a `system` field, look up its
   coordinates via a `system_coords` query (existing table, by name),
   compute distance, and produce one result row per matched material
   (`key_materials` entries, or `examples[]` entries for the HGE-shaped
   record — reuse nothing new here, `key_materials`/`examples` are
   already normalized fields on every loaded record).

2. **Live BGS-state matches**: query `faction_snapshots` (`is_controlling
   = 1`, most recent `snapshot_date` per system, joined to `systems` for
   `system_name` and `system_coords` for x/y/z — same JOIN chain
   `get_odyssey_farming_candidates()` already uses for the first two
   joins, extended with the coords join). For each row, derive a live
   tag set from `government`/`faction_state`/`active_states` — this
   needs a NEW function parallel to `_get_system_opportunities()` but
   reading from a DB row's fields instead of a live `state` object
   (call it `_tags_from_faction_snapshot_row(row)` in `intel_panel.py`,
   next to the other tag/matching functions, since the tag vocabulary
   and the guide-matching functions already live there and this reuses
   `_entry_matches_system()`/`_state_text_to_tags()` unchanged). For
   each guide record with `state_tags` or `examples`, call
   `_entry_matches_system(record, row_tags)` — non-empty means a match;
   for `examples`-bearing records, only the matched example(s) become
   result rows (same precision principle as the current-system fix).

If `material_filter` is given (case-insensitive substring match against
the material name), apply it before the final sort, not after — no
point computing distance for rows about to be discarded.

Merge both lists, sort by `distance_ly` ascending, truncate to `limit`
(display cap, not a distance cutoff — set once here in the repository
layer since the caller shouldn't need to know the cap value).

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

- `search_nearby_farming_opportunities()`: real-SQLite tests (tmp_path,
  matching this repo's established fixture pattern) — a static site at
  a known distance is found and correctly distanced; a live
  `faction_snapshots` row in a matching BGS state produces the right
  result with the right `state` value; a non-controlling faction's
  matching state does NOT produce a result (confirms the
  `is_controlling`-only scope choice); a `material_filter` narrows
  results correctly; results are sorted nearest-first; the `limit` cap
  is respected.
- `_tags_from_faction_snapshot_row()`: pure-function tests mirroring
  `_get_system_opportunities()`'s existing test style (module-level,
  no Qt), confirming it derives the same tag vocabulary from a DB-row
  shape.
- UI wiring/rendering: no automated test, matches this codebase's
  established convention for panel rendering — verified live.

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
