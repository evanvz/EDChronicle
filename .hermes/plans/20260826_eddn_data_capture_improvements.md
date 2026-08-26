# EDDN Data Capture Improvements Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Expand EDDN inbound capture (outfitting/shipyard schemas, richer Docked station metadata, coords from journal/1) and add listener diagnostics, so EDChronicle's own DB increasingly answers questions that currently require Inara/EDSM.

**Architecture:** All four features slot into the existing EDDN inbound pipeline — `eddn_listener.py` (schema/event routing) → Qt signal → `EddnMarketCache` buffer (dict-keyed dedupe) → periodic background flush → `Repository` upsert. No new threads, timers, or design patterns; each feature is one more buffer + one more `save_*` method. Diagnostics is a plain counter dict updated by the listener, surfaced in the status bar.

**Tech Stack:** Python 3.12, PyQt6 (Qt signals/slots), SQLite via existing `persistence/database.py` + `repository.py`, pytest.

---

## Current State (verified by code inspection)

- `eddn_listener.py:23-48` defines schema prefixes: journal, commodity, fcmaterials, fsssignaldiscovered. `_RELEVANT_EVENTS` = {FSDJump, Location, CarrierJump, Docked, CodexEntry}.
- `eddn_listener.py:217-227`: FSDJump/Location/CarrierJump journal messages already extract `StarPos` → `system_coords` (**recommendation #3 is already implemented** — dropped from this plan).
- `eddn_listener.py:226`: Docked messages routed to `station_seen` → `extract_station_info()` (in `edc/core/station_pads.py`) captures only name/type/pads-level info today.
- `EddnMarketCache` (`edc/core/eddn_market.py`) holds 9 buffers; flush every 45s via `_EddnFlushWorker` with its own Repository connection; synchronous `flush()` at shutdown.
- Schema migration pattern: `persistence/database.py` has per-feature `CREATE TABLE IF NOT EXISTS` blocks (~lines 85-291) + `schema_version` table + separate index `ensure_*` methods.
- Timestamps are normalized via `_normalize_ts()` at all ingest points (commit `0caf8e3`).
- Tests: 409 passing, run via `.venv/Scripts/python.exe -m pytest tests -q`. Test conventions: fixture DB in tmp_path, direct Repository assertions.

## EDDN Schema References (for implementer)

- `outfitting/1`: message body has `header` (uploaderID, softwareName, softwareVersion, gatewayTimestamp, gameVersion...), `message` with `systemName`, `stationName`, `marketId`, `horizons` (bool), `odyssey` (bool), `modules` (list of strings, e.g. `"hpt_pulselaser_fixed_small"`).
- `shipyard/1`: same shape, but `ships` (list of strings, e.g. `"side_winder"`).
- Journal `Docked` event fields: `StationName`, `StationType`, `MarketID`, `StationServices` (list of strings), `StationEconomies` (list of `{Name, Proportion}`), `DistFromStarLS`, `StationGovernment`, `StationAllegiance`, `SystemAddress`, `StarSystem`.

---

## Task 1: DB schema + repository for station services/economies

**Objective:** Store the new Docked-sourced station metadata.

**Files:**
- Modify: `persistence/database.py` (after the `station_info` block ~line 140)
- Modify: `persistence/schema.py` (~line 111)
- Modify: `persistence/repository.py`
- Test: `tests/test_station_services.py` (new)

**Step 1: Write failing test**

```python
"""Station services/economies capture from EDDN Docked sightings."""
from persistence.repository import Repository


def test_save_station_services_upserts(tmp_path):
    repo = Repository(tmp_path / "test.db")
    repo.save_station_services(
        market_id=3702356736,
        system_name="Shinrarta Dezhra",
        station_name="Jameson Memorial",
        services=["Commodity Exchange", "Outfitting", "Shipyard"],
        economies=[("High Tech", 0.9), ("Refinery", 0.1)],
        dist_from_star_ls=1234.5,
        timestamp="2026-08-26T18:00:00Z",
        source="eddn",
    )
    row = repo.get_station_services(3702356736)
    assert row is not None
    assert "Outfitting" in row["services"].split("|")
    assert row["dist_from_star_ls"] == 1234.5

    # Re-sighting with different data overwrites
    repo.save_station_services(
        market_id=3702356736, system_name="Shinrarta Dezhra",
        station_name="Jameson Memorial", services=["Commodity Exchange"],
        economies=[("High Tech", 1.0)], dist_from_star_ls=1234.5,
        timestamp="2026-08-27T18:00:00Z", source="eddn",
    )
    assert "Outfitting" not in repo.get_station_services(3702356736)["services"]
```

**Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_station_services.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'save_station_services'`

**Step 3: Implement**

Table (both `database.py` and `schema.py`):

```sql
CREATE TABLE IF NOT EXISTS station_services (
    market_id INTEGER PRIMARY KEY,
    system_name TEXT NOT NULL,
    station_name TEXT NOT NULL,
    services TEXT NOT NULL DEFAULT '',        -- '|'-joined
    economies TEXT NOT NULL DEFAULT '',       -- 'Name:Proportion' comma-joined
    dist_from_star_ls REAL,
    last_updated TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'eddn'
)
```

`Repository.save_station_services` / `get_station_services` follow the existing upsert pattern in `save_station_info_batch` (`repository.py` — copy its `INSERT ... ON CONFLICT DO UPDATE` shape). Economies serialized as `"High Tech:0.9,Refinery:0.1"`.

**Step 4:** Run tests — PASS. **Step 5:** Commit `feat: station services/economies table + repository`.

## Task 2: Harvest Docked metadata in listener + cache + flush

**Objective:** Route Docked services/economies fields through the existing pipeline.

**Files:**
- Modify: `edc/core/eddn_listener.py` (~line 226, Docked branch)
- Modify: `edc/core/eddn_market.py` (new `on_station_services_message` + buffer + flush block)
- Modify: `edc/ui/main_window.py` (~line 1946, wire the new signal)
- Test: `tests/test_station_services.py` (extend)

**Step 1: Failing test** — feed a realistic Docked journal/1 message body into `EddnMarketCache.on_station_services_message`, flush, assert DB row. Copy the message-shape test style from existing `tests/test_eddn_market*.py` (locate exact filename first; search `search_files pattern="EddnMarketCache" path="tests"`).

**Step 2:** Verify FAIL.

**Step 3: Implement**

- Listener: extend `extract_station_info()` OR (preferred — smaller diff) emit a new `station_services_seen = pyqtSignal(dict)` carrying the raw Docked `message` dict; keep `extract_station_info` untouched.
- Cache: `self._station_services_buffer: Dict[int, tuple]` keyed by market_id; `on_station_services_message` extracts `StationServices`, `StationEconomies`, `DistFromStarLS` (defensive `isinstance` checks, matching sibling methods); timestamps via `_normalize_ts`.
- Flush: add to `flush()` and `_EddnFlushWorker` args (`main_window.py:4400-4412` pattern — one more positional arg + `pop_buffers()` return).
- `main_window.py` signal wiring next to line 1946.

**Step 4:** Tests PASS (full suite). **Step 5:** Commit `feat: harvest station services/economies from EDDN Docked sightings`.

## Task 3: outfitting/1 + shipyard/1 capture — schema plumbing

**Objective:** Parse the two new schemas off the live feed.

**Files:**
- Modify: `edc/core/eddn_listener.py` (new prefix constants + routing)
- Test: `tests/test_eddn_outfitting.py` (new)

**Step 1: Failing test** — construct a minimal outfitting/1 and shipyard/1 message (schema refs `"https://eddn.edcd.io/schemas/outfitting/1"` / `.../shipyard/1`), feed through the listener's message-dispatch method (find its exact name/harness in existing listener tests: `search_files pattern="fcmaterials" path="tests"`), assert the new signals fire with parsed payload.

**Step 2:** Verify FAIL.

**Step 3: Implement**

```python
_OUTFITTING_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/outfitting/"
_SHIPYARD_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/shipyard/"
```

Routing mirrors the fcmaterials branch (`eddn_listener.py:196-203`). New signals: `outfitting_seen = pyqtSignal(dict)`, `shipyard_seen = pyqtSignal(dict)` — emit the full `message` dict; parsing lives in the cache (keeps listener dumb, matching existing style).

**Step 4:** Tests PASS. **Step 5:** Commit `feat: parse outfitting/1 and shipyard/1 EDDN schemas`.

## Task 4: outfitting/shipyard buffers, DB, flush

**Objective:** Persist module/ship availability per station.

**Files:**
- Modify: `persistence/database.py` + `persistence/schema.py` (two tables)
- Modify: `persistence/repository.py`
- Modify: `edc/core/eddn_market.py`
- Modify: `edc/ui/main_window.py`
- Test: `tests/test_eddn_outfitting.py` (extend)

**Tables:**

```sql
CREATE TABLE IF NOT EXISTS station_modules (
    market_id INTEGER PRIMARY KEY,
    system_name TEXT NOT NULL,
    station_name TEXT NOT NULL,
    modules TEXT NOT NULL DEFAULT '',   -- '|'-joined module ids
    last_updated TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'eddn'
)
CREATE TABLE IF NOT EXISTS station_ships (
    market_id INTEGER PRIMARY KEY,
    system_name TEXT NOT NULL,
    station_name TEXT NOT NULL,
    ships TEXT NOT NULL DEFAULT '',     -- '|'-joined ship ids
    last_updated TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'eddn'
)
```

Plus a `search_stations_selling_module(module_id)` and `search_stations_selling_ship(ship_id)` repository method each — bounding-box JOIN on `system_coords` exactly like `search_market_prices` (`repository.py:1766`), so results can be radius-filtered. Staleness cutoff: reuse `_market_data_cutoff()` (14 days — module stock at a station is as volatile as prices).

Cache buffers keyed by market_id; flush wiring identical to Task 2. Note: outfitting/shipyard messages are **full snapshots** (each message lists everything the station stocks), so upsert-replace semantics are exactly right.

**Steps:** failing test (cache ingest → flush → DB → search) → implement → full suite → commit `feat: store outfitting/shipyard availability from EDDN`.

## Task 5: Listener diagnostics counters

**Objective:** Know the feed is alive and what it's delivering.

**Files:**
- Modify: `edc/core/eddn_listener.py` (counter dict + `stats()` method)
- Modify: `edc/ui/main_window.py` (status bar line, updated on the existing 2-min `_eddn_save_timer` tick — no new timer)
- Test: `tests/test_eddn_listener_stats.py` (new)

**Design:**

```python
self.stats = {
    "messages_total": 0, "parse_errors": 0, "bytes_total": 0,
    "by_schema": {},   # {"journal/1": 1234, "commodity/3": 567, ...}
    "last_message_at": None,  # monotonic
}
```

Increment in the receive loop (single thread — no locking needed). `stats()` returns a snapshot copy. UI: extend the existing status string with e.g. `EDDN: 1.2k msg/s · journal 9k · commodity 1.4k · age 3s`. Keep it to one line, existing styling.

**Steps:** failing test (feed N mock messages → assert counters) → implement → full suite → commit `feat: EDDN listener diagnostics counters + status display`.

## Task 6 (optional, defer unless requested): UI for module/ship search

Out of scope for this plan — data capture only. The repository search methods (Task 4) are the seam a future panel plugs into. Do NOT build UI now (YAGNI).

---

## Validation / Verification

- Per-task: targeted `pytest tests/test_<file>.py -v` then full `.venv/Scripts/python.exe -m pytest tests -q` (all 409 + new must pass).
- Live verification (user, per project rules — features count as done only after live journal/EDDN testing):
  1. Run app overnight-ish session; check status line shows non-zero per-schema counts and age < 30s.
  2. `sqlite3` the DB: `SELECT COUNT(*) FROM station_services` / `station_modules` / `station_ships` grow over the session.
  3. Dock at a station with known services (e.g. Jameson Memorial — full services); after ≤45s+flush, row appears with correct services list.

## Risks / Tradeoffs / Open Questions

- **Volume:** outfitting/shipyard are lower-volume than commodity/3; buffering absorbs it. No risk to the 45s flush design.
- **DB growth:** two new per-station tables (upsert by market_id — bounded by station count, ~ tens of thousands of rows max). 14-day pruning applies via existing pruner? **Open:** the pruner (`prune_stale_market_prices` + friends) needs equivalent `prune_stale_station_modules/ships/services` — add to Task 4, mirroring `_bgs_status_cutoff` style (batched DELETE, 20k rows/commit).
- **Schema churn:** EDDN occasionally bumps schema versions; prefix-matching (no version pinning) already handles this.
- **Ordering:** Tasks 1-2 (Docked metadata) are independent of Tasks 3-4 (outfitting/shipyard) — can be done in either order or in parallel by two implementers. Task 5 independent.
- **Open question for user:** none blocking. Task 6 deliberately deferred.
