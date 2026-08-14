# Footfall Tracking Fix — Design

## Context

Follow-up to today's earlier fix (commit `601ec31`, `13a93a5`) for DSS-mapped status not being recognized live. Investigating a related user question ("does no footfall badge mean I'll get first footfall if I land?") surfaced that footfall tracking has two real bugs, distinct from the DSS one.

## Research

- **`WasFootfalled` is a real, server-authoritative field on the `Scan` journal event** (confirmed against the official schema, alongside `WasDiscovered`/`WasMapped`) — tells you, on every scan, whether *any* commander has ever footfalled on that body. The app currently never reads it.
- Footfall data (`HasFootfall`/`FirstFootfall`) only ever comes from a `Disembark` event, in `edc/core/event_engine.py`'s own inline event handling — meaning the app only knows about footfall if the *player personally* disembarked there. Zero visibility into other commanders.
- **Data-loss bug, confirmed by tracing the actual dispatch order:** `edc/engine/handlers/exploration.py`'s `handle()` is the Scan handler that actually wins (see "Known duplicate-code issue" below) and does a full dict replacement on `state.bodies[body_name]` with a fixed key set that excludes footfall fields entirely — so any Scan of a body *after* you've already disembarked there silently erases `HasFootfall`/`FirstFootfall`.
- The persisted `bodies` table already has `first_footfall`/`has_footfall` columns (used by `journal_importer.py`/`system_data_loader.py`, mirroring the `was_mapped`/`dss_mapped` pattern) — no new column needed for those, but nothing currently reads/persists `WasFootfalled` itself.

### Known duplicate-code issue (not fixed by this plan — noted per user request)

`edc/core/event_engine.py`'s `process()` method contains a large, unconditional inline `if name == "Location": ... elif name == "Scan": ... elif name == "Disembark": ...` chain (roughly lines 267–1990) that runs for *every* event, followed later in the *same method* by a separate, also-unconditional handler-chain loop (`for fn in (inventory.handle, exploration.handle, exobio.handle, ...): if fn(...): break`). For a `Scan` event, **both run**: the inline chain's Scan-handling first, then `exploration.handle` second (since `inventory.handle` doesn't match `Scan` and falls through). `exploration.handle` runs later and does a full-replace write, so it wins — making everything the inline chain's Scan branch does effectively dead code for fields `exploration.handle` also sets. This is the same class of duplication already noted once before in this codebase (ring-name handling). Worth a dedicated cleanup pass on its own; out of scope here to avoid an unrelated refactor riding along with a bug fix.

## Design

### 1. Live tracking — `edc/engine/handlers/exploration.py`

The Scan handler's `rec` dict construction gains:
- `"WasFootfalled": bool(event.get("WasFootfalled", False))` — read directly, same as `WasMapped`.
- `"HasFootfall": existing.get("HasFootfall", False)` and `"FirstFootfall": existing.get("FirstFootfall", False)` — preserved across re-scans via the same `existing.get(...)` fallback pattern already used for `BioSignals`/`GeoSignals`/`HumanSignals`/`BioGenuses`, fixing the data-loss bug. (These two still only ever get set `True` by the `Disembark` handling in `event_engine.py`'s inline chain — unaffected by this plan, still the only live source of "did *I* personally footfall here.")

### 2. Badge — `edc/ui/panels/exploration_panel.py`

Three states, checked in order:
1. `first_footfall` → gold "First Footfall" badge (personal credit, unchanged).
2. `has_footfall` (and not first) → grey "Footfall" badge (you've been there, unchanged).
3. Neither, but `was_footfalled` → new "Already Footfalled" badge (someone else has, you haven't) — distinct color from the personal-achievement badges so it doesn't read as your own accomplishment.
4. None of the above → no badge (genuinely unknown/likely-unfootfalled, same as today).

### 3. Persistence — mirrors `was_mapped`/`dss_mapped` exactly

- New `was_footfalled INTEGER DEFAULT 0` column on `bodies` (migration in `persistence/database.py::run_migrations()`).
- `Repository.save_body()` gains a `was_footfalled` parameter; `get_bodies()`'s column list includes it.
- `edc/ui/system_data_loader.py` rehydrates `state.bodies[...]["WasFootfalled"]` from the new column on system entry, same as `WasMapped`/`DSSMapped` already do.
- `edc/core/journal_importer.py`'s `_handle_scan` reads `WasFootfalled` from historical `Scan` events (mirrors its existing `was_mapped = int(bool(event.get("WasMapped", False)))` line) and passes it through to `save_body()`.

### Testing

`exploration.py`'s Scan handler: synthetic tests confirming `WasFootfalled` is read, and that `HasFootfall`/`FirstFootfall` survive a second Scan event for the same body (the actual data-loss repro). `journal_importer.py`: synthetic test confirming `was_footfalled` is parsed and persisted. Badge rendering: verified visually/headlessly per this file's established convention (no existing test file for `exploration_panel.py` render logic, matching prior sessions' approach for this tab).
