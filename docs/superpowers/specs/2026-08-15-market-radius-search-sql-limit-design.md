# Market Radius-Search SQL Variable Limit — Design

## Context

`persistence/repository.py:1464` (`search_fleet_carrier_materials`) crashed
with `sqlite3.OperationalError: too many SQL variables`, caught by the
Engineering tab's Wishlist card and logged rather than shown as a raw
traceback (`edc/ui/panels/engineering_panel.py:1145-1149`).

Root cause, confirmed by direct investigation against the live database
(not assumed):

- `_nearby_system_coords(x, y, z, radius_ly)` (`persistence/repository.py:1308`)
  runs a Python-side bounding-box `SELECT system_name, x, y, z FROM
  system_coords WHERE x BETWEEN ? AND ? AND ...`, then returns every
  matching row as a `{system_name: (x, y, z)}` dict.
- Every one of its 5 callers builds a SQL `IN (?,?,?...)` clause with one
  bound parameter per system name in that dict:
  `search_market_prices` (:1327), `search_market_prices_multi` (:1385),
  `search_fleet_carrier_materials` (:1442), `search_market_buy_prices`
  (:1495), `get_market_snapshot_in_radius` (:1549).
- `system_coords` is fed continuously by the EDDN listener — galaxy-wide,
  every commander's `FSDJump`/`Location` traffic — and is never pruned
  anywhere in the codebase (confirmed: no `DELETE FROM system_coords`
  exists). It had 437,726 rows after ~9 hours of the app running
  unattended, game not even open.
- At the user's configured `market_search_radius_ly=200`, the bounding
  cube around their last system (Ekono) contained 36,148 systems
  (confirmed via direct query against the live DB).
- This build's SQLite bound-parameter limit is 32,766 (confirmed via
  `conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)`). 36,148 exceeds
  it → crash. Fleet Carrier search hit the wall first only because it
  also adds material-symbol placeholders on top of the system-name ones;
  the other 4 callers are one `system_coords` growth-spurt away from the
  same failure.
- `EXPLAIN QUERY PLAN` on the bounding-box `SELECT` shows `SCAN
  system_coords` — a full table scan, no index, every call. Not the
  crash's cause, but the same code path and worth fixing alongside it.

A related, separate gap: `fleet_carrier_materials` rows are filtered out
of query results once older than 7 days (`_fleet_carrier_cutoff()`) but
are never `DELETE`d — unbounded growth, same class of problem as
`system_coords` had, just slower (carrier sightings are rarer than
galaxy-wide system traffic). `market_prices` already has this handled
(`prune_stale_market_prices()`, 30-day threshold, run daily from a
background `_MarketPruneWorker` — `edc/ui/main_window.py:152,1686-1707`).
User approved folding `fleet_carrier_materials` into the same worker
while this file is already being touched.

**Explicitly rejected:** splitting the database into separate functional
`.db` files. SQLite's bound-parameter limit is per-query, not per-file —
moving `system_coords` into its own file would not change how many `?`
placeholders land in any single query. Not part of this fix.

## Approach

Replace the "fetch every matching system name into Python, then build a
per-name `IN (...)` clause" pattern with a SQL-side `JOIN` against
`system_coords`, filtered by the same bounding box directly in the
database. Each query's bound-parameter count becomes fixed (roughly:
6 bounding-box bounds + the cutoff timestamp + however many material/
commodity symbols the caller passed) regardless of how large
`system_coords` ever grows — this stays correct at 4 million rows the
same as at 400 thousand, not just a bigger ceiling.

### `_nearby_system_coords` is deleted, not reused

Its only reason to exist was producing the `coords_by_system` dict each
caller used to (a) build the `IN (...)` clause and (b) look up per-row
`(x, y, z)` for the exact-sphere distance check after the SQL's looser
bounding-box prefilter. Both jobs move into each caller's own query and
result-row handling instead:

- The bounding box moves into the query's `WHERE` clause via the new
  `JOIN`.
- The `(x, y, z)` needed for the exact-distance check comes from the
  joined columns (`sc.x`, `sc.y`, `sc.z`) already present on each result
  row — no separate dict lookup needed.

### Query rewrite pattern (applied to all 5 callers)

Every caller's query currently joins `market_prices`/
`fleet_carrier_materials` (aliased `m`/`fcm`) to `station_info`
(aliased `si`) and filters `m.system_name IN ({placeholders})`. Add a
second join to `system_coords` (aliased `sc`) on system name, and
replace the `IN (...)` filter with the bounding-box `BETWEEN` filter,
pulling `sc.x, sc.y, sc.z` into the `SELECT` list:

```sql
-- before (search_market_prices, representative of all 5)
SELECT m.market_id, m.station_name, m.station_type, m.system_name,
       m.sell_price, m.demand, m.stock, m.last_updated,
       si.pads_small, si.pads_medium, si.pads_large, si.station_faction
FROM market_prices m
LEFT JOIN station_info si ON si.market_id = m.market_id
WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
      AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
      AND m.last_updated >= ?
      AND m.system_name IN ({placeholders})

-- after
SELECT m.market_id, m.station_name, m.station_type, m.system_name,
       m.sell_price, m.demand, m.stock, m.last_updated,
       si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
       sc.x, sc.y, sc.z
FROM market_prices m
INNER JOIN system_coords sc ON sc.system_name = m.system_name
LEFT JOIN station_info si ON si.market_id = m.market_id
WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
      AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
      AND m.last_updated >= ?
      AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
```

Bound params become `(commodity_name, cutoff, x-r, x+r, y-r, y+r, z-r,
z+r)` — 8 fixed values, never growing with table size. Python-side, each
result row already carries its own `(r["x"], r["y"], r["z"])` for the
exact-sphere distance check, replacing the old `coords_by_system[
r["system_name"]]` lookup.

`INNER JOIN` (not `LEFT`) is correct here: a `market_prices`/
`fleet_carrier_materials` row for a system with no `system_coords` entry
has no coordinates to filter or sort by, so it was already unreachable
under the old code too (`coords_by_system` came from `system_coords`;
a system absent from it never appeared in the old `IN (...)` list
either). Behavior is unchanged for that case, just expressed as a JOIN
condition instead of a precomputed Python list.

This pattern applies to all 5 functions with no other logic changes —
sorting, `exclude_market_id` filtering, pad-size resolution, and each
function's specific `SELECT` columns/grouping stay exactly as they are
today.

### New index

```sql
CREATE INDEX IF NOT EXISTS idx_system_coords_xyz ON system_coords(x, y, z)
```

**Correction to an earlier assumption in this doc:** `idx_market_prices_system_name`
is NOT in the flat `run_migrations()` list — re-checked directly against
`persistence/database.py`. It lives in its own method,
`Database.ensure_market_prices_indexes()` (`:52-64`), called only from
`_MarketVacuumWorker.run()` (`edc/ui/main_window.py:190-219`), i.e. only
when the user clicks Settings' "Compact Database Now" button. Its
docstring explains why: building it took ~2+ minutes at 13.4M rows,
needs a write lock, and `run_migrations()` runs synchronously on the
main/UI thread at every startup (`edc/ui/main_window.py:914`) — an
index build that slow would freeze the app on launch.

`system_coords` (437,726 rows and continuously, unboundedly growing)
is exactly the kind of table this concern applies to, even though it's
smaller than market_prices today. The new index follows the same
established pattern instead of the simpler flat-list one: a new
`Database.ensure_system_coords_indexes()` method (same shape as
`ensure_market_prices_indexes()`), called from the same
`_MarketVacuumWorker.run()` alongside the existing call — not from
`run_migrations()`.

This index is a performance improvement, not a correctness requirement
for the crash fix: the JOIN + `BETWEEN` query rewrite is what fixes the
crash (bound-parameter count is fixed regardless of whether SQLite
scans or seeks). Without the index, the bounding-box filter still
returns correct results via a full `system_coords` table scan — slower,
but the crash is fixed either way. Users who never click "Compact
Database Now" keep the crash fix; they just don't get the query-speed
improvement until they do (same tradeoff `market_prices` already
accepted for `idx_market_prices_system_name`, unchanged by this plan).

### `fleet_carrier_materials` pruning

New `Repository.prune_stale_fleet_carrier_materials() -> int` in
`persistence/repository.py`, sibling to the existing
`prune_stale_market_prices()`: `DELETE FROM fleet_carrier_materials
WHERE last_updated < ?` using the already-existing `_fleet_carrier_cutoff()`
(7-day threshold — same threshold the search queries already use, so
this doesn't change what search can find, only what's still on disk,
matching `prune_stale_market_prices()`'s own docstring reasoning).

`_MarketPruneWorker.run()` (`edc/ui/main_window.py:152-167`) gains a
second call to the new prune method, wrapped in its own `try/except`
(mirroring the existing call's exception handling) so a failure in one
prune doesn't prevent the other from running. The worker's existing
`finished = pyqtSignal(int)` emits the sum of both deleted counts — no
signal signature change, no new `QThread`/worker class needed. The
existing `_maybe_start_market_prune()`/`_on_market_prune_finished()`
scheduling (once/day, `cfg.last_market_prune_date`) covers both prunes
as one unit; log lines inside `run()` report each prune's count
separately before the combined emit, so the two remain individually
visible in the log even though the signal only carries the total.

## Testing

- Query rewrite: synthetic-testable — insert known `system_coords` +
  `market_prices`/`fleet_carrier_materials` rows spanning inside and
  outside a radius, confirm each of the 5 functions returns the same
  results before and after the rewrite (a direct regression check,
  since behavior must not change, only the query shape). Also test the
  specific case this bug report was about: a `system_coords` row count
  large enough that the *old* `IN (...)` approach would have exceeded
  32,766 bound parameters — confirm the new JOIN-based query still
  succeeds (this is the actual regression test for the crash itself,
  not just a refactor-safety check).
- Index: confirm `CREATE INDEX IF NOT EXISTS` is idempotent (run
  migrations twice, no error) — matches the existing test pattern for
  earlier migrations in this codebase, if one exists; otherwise a
  synthetic check is enough (query plan is not something to assert on
  in an automated test, per this codebase's existing comment on
  `idx_market_prices_system_name` treating that as a manual/live check).
- Fleet carrier prune: synthetic-testable — insert rows older and
  newer than the 7-day cutoff, confirm only the old ones are deleted
  and the count returned matches (mirrors whatever existing test
  pattern covers `prune_stale_market_prices`, if one exists in this
  codebase's test suite — reuse it, don't invent a new one).
- Worker wiring (`_MarketPruneWorker` gaining a second prune call): no
  automated UI/thread test expected, matches this codebase's established
  convention of live/visual verification for `main_window.py` wiring
  changes. Manual check: run the app, confirm the log shows both prune
  lines when the daily prune fires (or force it by clearing
  `last_market_prune_date` in settings).
- End-to-end: the original crash's actual trigger (Engineering tab →
  Wishlist card → material with unmet requirement → carrier search)
  should be re-run live once the fix lands, confirming no exception in
  the log and a populated (or correctly-empty) carrier table.

## Out of scope

- `get_market_snapshot_for_systems` (`persistence/repository.py:1625`)
  is a 6th `IN (...)`-based function but takes an exact caller-supplied
  system name list (Point-to-Point trade finder), not output from
  `_nearby_system_coords` — a different, bounded-by-design pattern, not
  touched by this fix.
- Database file splitting (rejected — see Context).
- Age-based pruning of `system_coords` itself (rejected — see Context;
  coordinates don't go stale, and EDDN traffic would refill any pruned
  rows regardless of the user's own travel history).
