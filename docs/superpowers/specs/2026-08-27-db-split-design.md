# Split the SQLite DB into personal + cache files — Design

## Context

This session root-caused a recurring live UI freeze to SQLite WAL
contention: the periodic EDDN flush (market prices, station info, BGS
status, etc.) and the main thread's continuous personal-journal writes
share one connection pool to one file (`edhelper.db`), and a WAL
checkpoint needs a brief exclusive lock across every connection touching
that file to fully drain. Two same-session fixes already shipped and are
confirmed live-fixed: batching outfitting/shipyard writes into one
transaction per flush (commit 4c43d5a), and moving the WAL checkpoint off
the 45s flush cadence onto its own 5-minute timer (commit f5cbae2). The
EDDN outfitting/shipyard *feature* itself was also removed outright
(commit 1d42faf) once it turned out to be the single largest contributor.

With the immediate pain gone, the commander (Evan) still wants the
underlying architectural fix, for three explicit reasons, in his own
words:

1. Keep personal journal data separate from "the rest."
2. Smaller/faster backup of the data that actually matters (personal
   history) — cache data is fully rebuildable from EDDN/Spansh/EDSM and
   has no business being backed up at all.
3. Performance headroom beyond tonight's stopgaps.

Explicitly **not** a goal: preserving existing rows in the cache tables
across the change. Evan has all his journal files and will delete/archive
the current `edhelper.db` before first launch on the new schema — the app
does a full rebuild (journal importer replays personal history, EDDN/
Spansh naturally repopulate the cache over live play). No migration
script that copies rows out of the old single-file DB is in scope.

A personal-EDSM-historical-data re-import (a separate capability EDChronicle
has never had — see project memory `project_edsm_personal_data_reimport`)
is explicitly deferred to after this work lands, not part of it.

## Research

### Every table, by actual write path (not assumption)

Verified against `persistence/schema.py` + `persistence/database.py`'s
migration list (27 tables total, the complete set) and every caller of
each `save_*`/`INSERT INTO` in `persistence/repository.py`, rather than
trusting docstrings — one correction this produced: `faction_snapshots`
looked EDDN-shaped at a glance (it's fed by `write_buffers()`'s `factions`
loop) but its EDDN contribution is gated to squadron-watched factions only
(`_maybe_emit_faction_seen`, rare by design) and it's also written
directly by three personal-journal/UI call sites (`main_window.py:578`,
`player_faction_panel.py:426/522/1533` — manual add, CSV import, daily
EDSM refresh). It's the backing store for the Player Faction tab's BGS
History, which EDSM cannot reconstruct after the fact (EDSM only exposes
*current* faction state, never historical daily snapshots) — genuinely
irreplaceable, stays personal. `spansh_bodies` and `commodity_names`
weren't in the original verbal proposal at all but are pure disposable
cache once actually checked.

**Personal DB** (`edhelper.db`, unchanged file, stays small):
`systems`, `system_coords`, `bodies`, `body_signals`, `exobiology`,
`codex_entries`, `dss_genus_discovery`, `processed_journals`,
`faction_snapshots`, `dismissed_faction_systems`, `rings`,
`colonisation_depots`, `resolved_bodies`, `schema_version`.

`systems`/`system_coords` stay personal even though EDDN/Spansh backfill
rows for systems never personally visited (`save_system_name_if_missing`,
`on_coords_seen`) — write volume is one upsert per *distinct system ever
seen*, not per-sighting, so it was never part of the contention problem,
and every other table on both sides of the split needs to reference it by
`system_address`/`system_name`/coords.

**Cache DB** (new `network_cache.db`, disposable, never backed up):
`market_prices`, `station_info`, `commodity_names`,
`fleet_carrier_materials`, `codex_species_sightings`,
`system_bgs_status`, `system_res_sites`, `spansh_bodies`.

Judgment call, flagged to and accepted by Evan: `station_info` also gets a
few rows from personal dockings (`main_window.py::_save_station_info`,
"most reliable source" for pad sizes at a station you've actually
visited) — moving it to the cache DB means that personal-confirmation
edge doesn't survive a restore, falling back to crowdsourced data until
next visit. Not catastrophic, matches the stated priority (small/fast
backup over completeness).

`market_prices`/`fleet_carrier_materials` confirmed to have **no**
personal-journal write path at all (`grep` for a non-`_batch` save method
outside `eddn_market.py`'s `write_buffers()` came back empty) — purely
EDDN.

### Threading model (unchanged by this design)

Every `Database(self._db_path)` call already opens its own connection per
the project's cross-thread SQLite rule (`CLAUDE.md`) — main thread's
long-lived `self.db`/`self.repo`, plus a fresh short-lived connection per
background worker (`_EddnFlushWorker`, `_WalCheckpointWorker`,
`_SpanshEnrichWorker`, `_MarketPruneWorker`, and every panel's own search
worker: `market_panel.py`, `trade_route_panel.py`,
`player_faction_panel.py`, `mining_panel.py`,
`combat_bgs_status_panel.py`). None of these construction call sites need
to change — see Design below.

### Existing retention precedent

`_market_data_cutoff()` (14 days) already gates `market_prices`/
`station_info` at search time and in `prune_stale_market_prices()` —
independent of file boundaries, a WHERE-clause constant. Evan asked to
extend this to 21 days now that it no longer weighs on the personal
backup.

## Design

### Two files, one connection, `ATTACH DATABASE`

`Database.__init__` opens `edhelper.db` as `main` (as today) and
immediately runs `ATTACH DATABASE '<network_cache.db path>' AS net`. This
is the only change every one of the dozen-plus `Database()` call sites
needs — none of them are touched, they all get both files automatically
through the one class.

`persistence/repository.py` gets the `net.` schema prefix added to SQL
referencing the 8 moved tables only (e.g. `net.market_prices`,
`net.station_info`). Every query that currently joins a moved table
against `system_coords` (market search, trade routes, combat BGS status
search) keeps working as plain SQL — `ATTACH` makes a JOIN across `main`
and `net` schemas transparent within one connection. No query gets
rewritten into two queries + an app-side merge.

Each attached file keeps its own independent WAL/lock even under one
connection — a write to `net.market_prices` only takes `network_cache.db`'s
lock, a write to `bodies` only takes `edhelper.db`'s. This is the actual
mechanism that eliminates the contention, not just a smaller symptom
window like tonight's stopgap.

**Invariant this design relies on**: no single transaction should span
both `main` and `net` tables. SQLite technically supports atomic
cross-schema transactions on one connection, so nothing breaks if this is
violated, but a transaction that touches both files re-couples their
locking for its duration — exactly the problem being solved. Verified
during Research that no current write path does this: `write_buffers()`'s
per-table save calls (market, station info, BGS status, etc.) each land
entirely in `net.` tables, and the `factions` loop's two calls
(`save_system_name_if_missing` then `save_faction_snapshot`) both target
`main.` tables (`systems`, `faction_snapshots`) — nothing currently
issues a write to a `net.` table and a `main.` table inside the same
transaction. Flag this explicitly in code review for any future addition.

### Two independent migration lists

`persistence/database.py`'s `run_migrations()` currently runs one ordered
list against one connection. Split into two lists, each run against its
own schema:

- `edhelper.db`'s list drops the 8 moved tables' `CREATE TABLE`/`ALTER
  TABLE` entries entirely (they're created in the cache file's list
  instead) and gains `DROP TABLE IF EXISTS <table>` for each of the 8 —
  cheap, idempotent cleanup if Evan runs the new build against his
  existing un-wiped `edhelper.db` instead of deleting it first. This is
  defensive, not the data-continuity plan (see Context).
- `network_cache.db`'s list is a fresh `CREATE TABLE IF NOT EXISTS` for
  each of the 8 tables, using their current column definitions verbatim
  (no schema changes to the tables themselves, only which file they live
  in).

`schema_version`/`_apply_version_migrations()`'s version-gated
re-import-required mechanism stays scoped to `edhelper.db` only — the
cache DB has no equivalent concept, since nothing in it needs a "personal
data might be stale, re-import journals" gate.

### Checkpoint worker

`_WalCheckpointWorker` (main_window.py) runs `PRAGMA
main.wal_checkpoint(TRUNCATE)` then `PRAGMA net.wal_checkpoint(TRUNCATE)`
as two separate statements on its one connection. The personal DB's
checkpoint becomes close to a no-op (write volume there is now just
personal journal events + the rare EDDN faction-watch trickle); the cache
DB's is where the real contention relief lives, still on its own 5-minute
timer per the existing stopgap.

### Retention

`_market_data_cutoff()` constant changes from 14 to 21 days. No other
retention logic changes — BGS/RES search-time filtering (7-day
War/CivilWar, 14-day RES presence) already matches the game's own weekly
BGS tick and is unaffected by which file the tables live in.

### Error handling

If `network_cache.db` is missing (first launch on the new schema, or
Evan deleted it deliberately) `CREATE TABLE IF NOT EXISTS` in its
migration list creates it fresh — same as `edhelper.db` does today, no
special case needed. If `ATTACH` itself fails (e.g. the file exists but
is corrupted), `Database.__init__` should catch it, log a warning, delete
the file, and retry the attach once rather than propagating a fatal
error — cache data is by design disposable, so this must never risk the
personal DB or crash the app. Needs a live-ish test: point `Database` at
a deliberately-corrupted cache file and confirm it self-heals instead of
raising.

### Testing

Every existing test fixture (`db.executescript(SCHEMA_SQL);
db.run_migrations()` against one `Database(tmp_path / "test.db")`) should
need **no changes** if `Database.__init__`/`run_migrations()` correctly
derives the cache file's path from the personal one internally (e.g.
same directory, fixed sibling filename) rather than requiring a second
path argument — this needs confirming once actually in the code, and is
the detail most likely to surprise implementation. If it turns out a
second path has to be threaded through, that's a much larger test-fixture
touch and should come back to this spec before proceeding.

New tests needed: cross-schema JOIN correctness (a market search result
correctly joins `net.market_prices` against `main.system_coords`), the
corrupted-cache-file self-heal path above, and that a personal-only write
(e.g. `save_body`) never touches `network_cache.db` at all (guards the
"no transaction spans both files" invariant staying true going forward).

## Non-Goals

- A third (or more) cache file split by retention/churn profile — Evan
  raised this and we agreed 2 files fully covers the three stated goals;
  more files add real complexity (another ATTACH, another checkpoint
  target, another migration list) without buying more separation,
  smaller backup, or performance than 2 already provides.
- A live migration path that copies existing cache-table rows out of the
  current `edhelper.db` into the new cache file — explicitly rejected in
  favor of rebuild-from-journal (see Context).
- The EDSM personal-historical-data re-importer — separate, deferred
  future work (tracked in memory, not this spec).
- Any change to what data is collected, cross-referenced, or how the
  Spansh/EDSM/EDDN enrichment logic itself works — this is a storage
  relocation only, behavior is unchanged.
