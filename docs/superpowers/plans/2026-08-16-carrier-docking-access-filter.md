# Fleet Carrier Docking Access Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude Fleet Carriers with confirmed-restricted docking access from the Engineering tab's "SOLD BY CARRIERS" results, and label the rest "Open" or "Unknown" access, using EDDN commodity/3's optional `carrierDockingAccess` field — the only data source that can ever answer this for another commander's carrier.

**Architecture:** A 7th in-memory buffer in `EddnMarketCache` captures `carrierDockingAccess` from commodity messages, flushed to a new `station_info.carrier_docking_access` column (same per-`market_id` granularity as the rest of that table). `search_fleet_carrier_materials()` filters out confirmed-restricted carriers and surfaces the raw value to the UI, which renders it as a new "Access" column on both carrier tables.

**Tech Stack:** Python, SQLite (via existing `Repository`/`Database` wrapper), PyQt6, pytest with a real temp-file SQLite fixture (existing pattern, no mocks).

## Global Constraints

- No new dependency, no new table — `station_info` (already one row per `market_id`) gets one new nullable column.
- Filter semantics: exclude only *confirmed*-restricted (`carrier_docking_access` present and not `'all'`); keep confirmed-open (`'all'`) and unknown (`NULL`) — per explicit user decision, unknown carriers still show, just labeled.
- UI colors: `"Open"` → `QColor("#6BCB77")`, `"Unknown"` → `QColor("#888888")` — this exact pairing already exists at `edc/ui/panels/engineering_panel.py:1047-1050` for an analogous confirmed/unknown cell; reuse verbatim, do not invent new hex values.
- Spec of record: `docs/superpowers/specs/2026-08-16-carrier-docking-access-filter-design.md`.

---

### Task 1: Ingestion buffer + schema + repository

**Files:**
- Modify: `edc/core/eddn_market.py` (all of it — `__init__`, `on_commodity_message`, `buffered_counts`, `pop_buffers`, `flush`, `write_buffers`)
- Modify: `persistence/database.py` (`run_migrations`, ~line 150)
- Modify: `persistence/repository.py` (new method + `search_fleet_carrier_materials`, currently lines 1486-1542)
- Test: `tests/test_carrier_docking_access.py` (new)

**Interfaces:**
- Produces: `EddnMarketCache.pop_buffers()` now returns a 7-tuple `(coords, market, factions, stations, codex, fcmaterials, carrier_access)` (was 6-tuple) — `carrier_access` is `list[tuple[int, str, str]]`, each `(market_id, docking_access, timestamp)`.
- Produces: `write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access)` — same new 7th parameter, same position.
- Produces: `Repository.save_carrier_docking_access_batch(self, records: list[tuple]) -> None` — `records` shape `[(market_id, docking_access, timestamp), ...]`.
- Produces: `Repository.search_fleet_carrier_materials(...)` — unchanged signature, but each returned listing dict now has a `"docking_access"` key (`None` or `"all"` — confirmed-restricted rows never reach the caller at all, filtered in SQL).
- Consumes: nothing new from other tasks — this task is self-contained.

This task's `EddnMarketCache`/`write_buffers` interface changes are consumed by Task 2 (`main_window.py`'s `_EddnFlushWorker` and its call site). Task 3 consumes only the `"docking_access"` key on `search_fleet_carrier_materials()`'s return value, independent of Task 2.

- [ ] **Step 1: Write the failing repository tests**

Create `tests/test_carrier_docking_access.py`:

```python
"""Tests for Repository.save_carrier_docking_access_batch() and
search_fleet_carrier_materials()'s docking-access filter -- real SQLite
(temp file), not mocks, matching this repo's established pattern (see
tests/test_fleet_carrier_materials.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_station(repo, market_id, system_name, station_type="FleetCarrier"):
    repo.save_station_info_batch([{
        "market_id": market_id,
        "station_name": "Test Carrier",
        "system_name": system_name,
        "station_type": station_type,
        "pads_small": None,
        "pads_medium": None,
        "pads_large": 1,
        "timestamp": "2026-08-12T00:00:00Z",
    }])


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_material(repo, market_id, symbol, price=1000, stock=5, demand=0,
                    last_updated=_FRESH, carrier_name="Test Carrier", carrier_id="ABC-123"):
    repo.save_fleet_carrier_materials_batch([
        (market_id, symbol, carrier_name, carrier_id, price, stock, demand, last_updated)
    ])


# --- save_carrier_docking_access_batch() ---

def test_save_carrier_docking_access_inserts_skeletal_row_when_none_exists(repo):
    # No _seed_station() call -- simulates a commodity/3 sighting arriving
    # before any Docked sighting for this market_id.
    repo.save_carrier_docking_access_batch([(1001, "all", "2026-08-12T00:00:00Z")])
    row = repo.db.conn.execute(
        "SELECT market_id, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["market_id"] == 1001
    assert row["carrier_docking_access"] == "all"


def test_save_carrier_docking_access_updates_existing_row_without_clobbering_other_columns(repo):
    _seed_station(repo, 1001, "Sol")
    repo.save_carrier_docking_access_batch([(1001, "friends", "2026-08-12T00:00:00Z")])
    row = repo.db.conn.execute(
        "SELECT system_name, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["system_name"] == "Sol"
    assert row["carrier_docking_access"] == "friends"


def test_docked_sighting_after_docking_access_does_not_clobber_it(repo):
    # Order-independence: a commodity/3 sighting (docking access) arriving
    # BEFORE a Docked sighting (station_info's other fields) must survive
    # that later Docked upsert untouched.
    repo.save_carrier_docking_access_batch([(1001, "squadron", "2026-08-12T00:00:00Z")])
    _seed_station(repo, 1001, "Sol")
    row = repo.db.conn.execute(
        "SELECT system_name, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["system_name"] == "Sol"
    assert row["carrier_docking_access"] == "squadron"


# --- search_fleet_carrier_materials() docking-access filter ---

def test_confirmed_open_carrier_is_included(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    repo.save_carrier_docking_access_batch([(1001, "all", "2026-08-12T00:00:00Z")])

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["docking_access"] == "all"


def test_unknown_access_carrier_is_included(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    # No save_carrier_docking_access_batch() call at all.

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["docking_access"] is None


@pytest.mark.parametrize("restricted_value", ["friends", "squadron", "squadronfriends", "none"])
def test_confirmed_restricted_carrier_is_excluded(repo, restricted_value):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    repo.save_carrier_docking_access_batch([(1001, restricted_value, "2026-08-12T00:00:00Z")])

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_carrier_docking_access.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'save_carrier_docking_access_batch'` (and `sqlite3.OperationalError: no such column: carrier_docking_access` once that's fixed next).

- [ ] **Step 3: Add the schema migration**

In `persistence/database.py`, re-read `run_migrations()` fresh to confirm current line numbers, then add this line immediately after the existing `"ALTER TABLE station_info ADD COLUMN station_faction TEXT",` line (grouping it with the other `station_info` migrations):

```python
            "ALTER TABLE station_info ADD COLUMN carrier_docking_access TEXT",
```

- [ ] **Step 4: Add `Repository.save_carrier_docking_access_batch`**

In `persistence/repository.py`, add this new method immediately after `save_fleet_carrier_materials_batch` (currently ending at line 926):

```python
    def save_carrier_docking_access_batch(self, records: list[tuple]):
        """
        records: [(market_id, docking_access, timestamp), ...] -- from EDDN
        commodity/3's optional carrierDockingAccess field. Upserts only the
        carrier_docking_access column on station_info; if no row exists yet
        for this market_id (no Docked sighting seen), inserts a skeletal
        row with just market_id + this column -- a later Docked sighting's
        own upsert (save_station_info_batch) fills in the rest without
        touching this column. Harmless either arrival order.
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO station_info (market_id, carrier_docking_access)
            VALUES (?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                carrier_docking_access = excluded.carrier_docking_access
            """,
            [(market_id, access) for market_id, access, _ts in records],
        )
        self.db.conn.commit()
```

- [ ] **Step 5: Update `search_fleet_carrier_materials`**

Re-read `persistence/repository.py` around `search_fleet_carrier_materials` (currently lines 1486-1542) fresh, then change its SQL query (currently lines 1508-1526) from:

```python
        rows = self.db.conn.execute(
            f"""
            SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
                   fcm.stock, fcm.demand, fcm.last_updated,
                   si.market_id, si.system_name, si.last_visited,
                   sc.x, sc.y, sc.z
            FROM fleet_carrier_materials fcm
            INNER JOIN station_info si ON si.market_id = fcm.market_id
            INNER JOIN system_coords sc ON sc.system_name = si.system_name
            WHERE fcm.material_symbol IN ({sym_placeholders})
                  AND fcm.stock > 0
                  AND fcm.last_updated >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                *material_symbols, _fleet_carrier_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()
```

to:

```python
        rows = self.db.conn.execute(
            f"""
            SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
                   fcm.stock, fcm.demand, fcm.last_updated,
                   si.market_id, si.system_name, si.last_visited,
                   si.carrier_docking_access AS docking_access,
                   sc.x, sc.y, sc.z
            FROM fleet_carrier_materials fcm
            INNER JOIN station_info si ON si.market_id = fcm.market_id
            INNER JOIN system_coords sc ON sc.system_name = si.system_name
            WHERE fcm.material_symbol IN ({sym_placeholders})
                  AND fcm.stock > 0
                  AND fcm.last_updated >= ?
                  AND (si.carrier_docking_access IS NULL OR si.carrier_docking_access = 'all')
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                *material_symbols, _fleet_carrier_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()
```

(Only the two additions — the new SELECT column with its `AS docking_access` alias, and the new `WHERE` clause line — nothing else in this method changes; `rec = dict(r)` further down already copies every selected column into the returned dict automatically, so `"docking_access"` appears on each listing dict with no further code change needed.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_carrier_docking_access.py tests/test_fleet_carrier_materials.py -v`
Expected: all PASS — the new tests confirm the new method and filter; `test_fleet_carrier_materials.py` (unchanged) confirms no regression to the existing search behavior (every one of its seeded carriers has no `carrier_docking_access` row, so they all fall into the "unknown, included" bucket, exactly as before this change).

- [ ] **Step 7: Add the 7th buffer to `EddnMarketCache`**

Re-read `edc/core/eddn_market.py` fresh, then make these changes:

In `__init__` (currently lines 30-47), add after the existing `self._fcmaterials_buffer` line:

```python
        # Keyed by market_id -- a carrier's self-reported docking access
        # from commodity/3's optional carrierDockingAccess field, any
        # commander's. The only data source that can ever answer "can I
        # land here" for someone else's carrier (see module docstring
        # context in this task's design spec) -- coverage is necessarily
        # incomplete since the field is optional.
        self._carrier_access_buffer: Dict[int, Tuple[int, str, str]] = {}
```

In `on_commodity_message` (currently lines 56-78), add this block right after the existing `timestamp = msg.get("timestamp") or ""` line, before the `for c in (msg.get("commodities") or []):` loop:

```python
        docking_access = msg.get("carrierDockingAccess")
        if isinstance(docking_access, str) and docking_access:
            self._carrier_access_buffer[market_id] = (market_id, docking_access, timestamp)
```

Change `buffered_counts` (currently lines 122-127) from:

```python
    def buffered_counts(self) -> Tuple[int, int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count, station_count, fcmaterials_count) currently buffered — for status/logging."""
        return (
            len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer),
            len(self._station_buffer), len(self._fcmaterials_buffer),
        )
```

to:

```python
    def buffered_counts(self) -> Tuple[int, int, int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count, station_count, fcmaterials_count, carrier_access_count) currently buffered — for status/logging."""
        return (
            len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer),
            len(self._station_buffer), len(self._fcmaterials_buffer), len(self._carrier_access_buffer),
        )
```

Change `pop_buffers` (currently lines 129-149) from:

```python
    def pop_buffers(self):
        """
        Snapshots and clears all six buffers, returning their contents as
        plain lists/tuples — for handing off to a background worker with
        its own DB connection (see main_window.py's _EddnFlushWorker).
        Cheap, main-thread-only dict operations; the actual DB writes are
        the expensive part, deliberately not done here.
        """
        coords = list(self._coord_buffer.values())
        market = list(self._market_buffer.values())
        factions = list(self._faction_buffer.items())
        stations = list(self._station_buffer.values())
        codex = list(self._codex_buffer.values())
        fcmaterials = list(self._fcmaterials_buffer.values())
        self._coord_buffer.clear()
        self._market_buffer.clear()
        self._faction_buffer.clear()
        self._station_buffer.clear()
        self._codex_buffer.clear()
        self._fcmaterials_buffer.clear()
        return coords, market, factions, stations, codex, fcmaterials
```

to:

```python
    def pop_buffers(self):
        """
        Snapshots and clears all seven buffers, returning their contents as
        plain lists/tuples — for handing off to a background worker with
        its own DB connection (see main_window.py's _EddnFlushWorker).
        Cheap, main-thread-only dict operations; the actual DB writes are
        the expensive part, deliberately not done here.
        """
        coords = list(self._coord_buffer.values())
        market = list(self._market_buffer.values())
        factions = list(self._faction_buffer.items())
        stations = list(self._station_buffer.values())
        codex = list(self._codex_buffer.values())
        fcmaterials = list(self._fcmaterials_buffer.values())
        carrier_access = list(self._carrier_access_buffer.values())
        self._coord_buffer.clear()
        self._market_buffer.clear()
        self._faction_buffer.clear()
        self._station_buffer.clear()
        self._codex_buffer.clear()
        self._fcmaterials_buffer.clear()
        self._carrier_access_buffer.clear()
        return coords, market, factions, stations, codex, fcmaterials, carrier_access
```

Change `flush` (currently lines 151-162) from:

```python
    def flush(self) -> None:
        """Synchronous flush on the caller's own thread/connection — only
        safe to call from the main thread (uses self._repo, the main
        thread's connection) and only when blocking briefly is acceptable
        (e.g. on app shutdown). The periodic mid-session flush uses
        pop_buffers() + write_buffers() on a background worker instead —
        this was previously a QTimer-connected slot running directly on
        the main thread every 45s, which froze the UI for however long a
        big buffered batch took to write (confirmed live, worse right
        after docking at a busy station's market)."""
        coords, market, factions, stations, codex, fcmaterials = self.pop_buffers()
        write_buffers(self._repo, coords, market, factions, stations, codex, fcmaterials)
```

to:

```python
    def flush(self) -> None:
        """Synchronous flush on the caller's own thread/connection — only
        safe to call from the main thread (uses self._repo, the main
        thread's connection) and only when blocking briefly is acceptable
        (e.g. on app shutdown). The periodic mid-session flush uses
        pop_buffers() + write_buffers() on a background worker instead —
        this was previously a QTimer-connected slot running directly on
        the main thread every 45s, which froze the UI for however long a
        big buffered batch took to write (confirmed live, worse right
        after docking at a busy station's market)."""
        coords, market, factions, stations, codex, fcmaterials, carrier_access = self.pop_buffers()
        write_buffers(self._repo, coords, market, factions, stations, codex, fcmaterials, carrier_access)
```

Change `write_buffers` (currently lines 165-208) from:

```python
def write_buffers(repo, coords, market, factions, stations, codex, fcmaterials) -> None:
    """The actual writes — factored out so both the main-thread flush()
    (shutdown) and a background worker (periodic, see main_window.py) can
    use the identical logic against whichever Repository they're given."""
```

to:

```python
def write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access) -> None:
    """The actual writes — factored out so both the main-thread flush()
    (shutdown) and a background worker (periodic, see main_window.py) can
    use the identical logic against whichever Repository they're given."""
```

and add this block at the end of the function, after the existing `if fcmaterials:` block (currently lines 204-208):

```python

    if carrier_access:
        try:
            repo.save_carrier_docking_access_batch(carrier_access)
        except Exception:
            log.exception("Failed to flush carrier_docking_access batch")
```

- [ ] **Step 8: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/core/eddn_market.py', encoding='utf-8').read()); ast.parse(open('persistence/repository.py', encoding='utf-8').read()); ast.parse(open('persistence/database.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 9: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS. Note: `edc/core/eddn_market.py`'s buffer plumbing itself (steps 7's changes) has no existing dedicated test file in this repo (confirmed: no `tests/*eddn_market*` file exists) and this task does not add one, matching this codebase's established convention of not testing pure wiring/plumbing when no existing precedent does — Step 10 below is this task's verification for that piece instead.

- [ ] **Step 10: Manual buffer round-trip smoke check**

Run this to confirm the widened tuple arity round-trips correctly end to end, independent of any Qt/EDDN network connection:

```
.venv/Scripts/python.exe -c "
import tempfile, os
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.core.eddn_market import EddnMarketCache, write_buffers

tmp = tempfile.mktemp(suffix='.db')
db = Database(tmp)
db.executescript(SCHEMA_SQL)
db.run_migrations()
repo = Repository(db)

cache = EddnMarketCache(repo)
cache.on_commodity_message({
    'marketId': 9001, 'stationName': 'Test Carrier', 'stationType': 'FleetCarrier',
    'systemName': 'Sol', 'timestamp': '2026-08-16T00:00:00Z', 'commodities': [],
    'carrierDockingAccess': 'all',
})
counts = cache.buffered_counts()
assert counts == (0, 0, 0, 0, 0, 1), counts
bufs = cache.pop_buffers()
assert len(bufs) == 7, len(bufs)
write_buffers(repo, *bufs)
row = db.conn.execute('SELECT carrier_docking_access FROM station_info WHERE market_id = 9001').fetchone()
assert row['carrier_docking_access'] == 'all', dict(row) if row else None
print('OK: 7-tuple buffer round-trip works end to end')
db.close()
os.remove(tmp)
"
```

Expected output: `OK: 7-tuple buffer round-trip works end to end`

- [ ] **Step 11: Commit**

```bash
git add edc/core/eddn_market.py persistence/database.py persistence/repository.py tests/test_carrier_docking_access.py
git commit -m "feat: capture carrier docking access from EDDN and filter restricted carriers from search"
```

---

### Task 2: Thread the 7th buffer through `main_window.py`'s flush worker

**Files:**
- Modify: `edc/ui/main_window.py` (`_EddnFlushWorker` class ~lines 284-316, `_on_market_flush_tick` ~lines 3990-4007)

**Interfaces:**
- Consumes: `EddnMarketCache.pop_buffers()` returning a 7-tuple and `write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access)` (both from Task 1, `edc/core/eddn_market.py`).
- Produces: nothing new — this task only threads an existing interface change through its remaining call sites.

This task exists separately from Task 1 specifically to keep the `eddn_market.py`-internal change (Task 1) isolated from this large, easy-to-get-wrong plumbing update in a different, frequently-stale file — a mismatched tuple arity across `main_window.py`'s multiple call sites is exactly the class of bug that's easy to introduce if bundled with Task 1's other work.

- [ ] **Step 1: Re-read `main_window.py` fresh and update `_EddnFlushWorker`**

Re-read `edc/ui/main_window.py` around lines 284-316 fresh (this file is on the project's frequently-stale list — always re-read before editing) to confirm current line numbers, then change `_EddnFlushWorker.__init__` and `run` from:

```python
    def __init__(self, db_path, coords, market, factions, stations, codex, fcmaterials):
        super().__init__()
        self._db_path = db_path
        self._coords, self._market, self._factions = coords, market, factions
        self._stations, self._codex, self._fcmaterials = stations, codex, fcmaterials

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            write_buffers(repo, self._coords, self._market, self._factions, self._stations, self._codex, self._fcmaterials)
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            log.exception("Background EDDN flush failed")
        finally:
            db.close()
        self.finished.emit()
```

to:

```python
    def __init__(self, db_path, coords, market, factions, stations, codex, fcmaterials, carrier_access):
        super().__init__()
        self._db_path = db_path
        self._coords, self._market, self._factions = coords, market, factions
        self._stations, self._codex, self._fcmaterials = stations, codex, fcmaterials
        self._carrier_access = carrier_access

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            write_buffers(
                repo, self._coords, self._market, self._factions, self._stations,
                self._codex, self._fcmaterials, self._carrier_access,
            )
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            log.exception("Background EDDN flush failed")
        finally:
            db.close()
        self.finished.emit()
```

- [ ] **Step 2: Update `_on_market_flush_tick`**

In the same file, re-read around lines 3990-4007 fresh, then change:

```python
    def _on_market_flush_tick(self) -> None:
        """
        Pops the buffered EDDN data (cheap, main-thread dict ops) and hands
        it to a background worker for the actual writes + WAL checkpoint —
        see _EddnFlushWorker for why this moved off the main thread.
        """
        if self._flush_thread and self._flush_thread.isRunning():
            return  # previous flush still running — next tick will catch up
        coords, market, factions, stations, codex, fcmaterials = self.eddn_market_cache.pop_buffers()
        if not (coords or market or factions or stations or codex or fcmaterials):
            return

        self._flush_worker = _EddnFlushWorker(self.repo.db.db_path, coords, market, factions, stations, codex, fcmaterials)
        self._flush_thread = QThread()
        self._flush_worker.moveToThread(self._flush_thread)
        self._flush_thread.started.connect(self._flush_worker.run)
        self._flush_worker.finished.connect(self._flush_thread.quit)
        self._flush_thread.start()
```

to:

```python
    def _on_market_flush_tick(self) -> None:
        """
        Pops the buffered EDDN data (cheap, main-thread dict ops) and hands
        it to a background worker for the actual writes + WAL checkpoint —
        see _EddnFlushWorker for why this moved off the main thread.
        """
        if self._flush_thread and self._flush_thread.isRunning():
            return  # previous flush still running — next tick will catch up
        coords, market, factions, stations, codex, fcmaterials, carrier_access = self.eddn_market_cache.pop_buffers()
        if not (coords or market or factions or stations or codex or fcmaterials or carrier_access):
            return

        self._flush_worker = _EddnFlushWorker(
            self.repo.db.db_path, coords, market, factions, stations, codex, fcmaterials, carrier_access,
        )
        self._flush_thread = QThread()
        self._flush_worker.moveToThread(self._flush_thread)
        self._flush_thread.started.connect(self._flush_worker.run)
        self._flush_worker.finished.connect(self._flush_thread.quit)
        self._flush_thread.start()
```

- [ ] **Step 3: Verify no other call site was missed**

Run: `grep -n "_EddnFlushWorker(\|\.pop_buffers()\|write_buffers(" edc/ui/main_window.py`
Expected: exactly the two call sites just edited (the `_EddnFlushWorker(...)` construction and the `pop_buffers()` unpack), both showing 7 elements — plus `self.eddn_market_cache.flush()` at the shutdown path (~line 1665), which needs no edit since `flush()` itself (Task 1) already calls `self.pop_buffers()`/`write_buffers()` internally with matching arity.

- [ ] **Step 4: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS — no regression to any other `main_window.py`-dependent test.

- [ ] **Step 6: Manual verification note**

This task's actual runtime correctness (does a real periodic flush tick work end to end inside the running app) can only be confirmed by launching the app — note this as pending for a human; a subagent cannot do it. Task 1's Step 10 already confirmed the underlying buffer/write-path arity works correctly outside of Qt, which covers the logic this task threads through.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "fix: thread the new carrier-docking-access buffer through the EDDN flush worker"
```

---

### Task 3: UI — "Access" column on both carrier tables

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py` (Ships tab: header/table setup ~lines 311-324, `_refresh_carrier_table` ~lines 606-681; Suits & Weapons tab: header/table setup ~lines 856-869, `_refresh_carrier_table` ~lines 1118-~1190)

**Interfaces:**
- Consumes: `Repository.search_fleet_carrier_materials(...)` (Task 1) — each returned listing dict now has a `"docking_access"` key (`None` or `"all"`).
- Produces: nothing new — UI-only, terminal task.

This task is independent of Task 2 (it only touches the read/search/display path, never the EDDN ingestion plumbing) — it depends only on Task 1's `"docking_access"` key.

This codebase has no Qt test fixture (no `QApplication` anywhere in `tests/`) — this task has no automated test and ends with a manual live-verification step a human must do.

- [ ] **Step 1: Re-read `engineering_panel.py` fresh**

Re-read `edc/ui/panels/engineering_panel.py` in full around all four locations below (this file is not on the project's frequently-stale list, but re-read fresh anyway per this session's established practice) to confirm current line numbers before editing — this file has two nearly-identical copies of the same carrier-table code (Ships tab and Suits & Weapons tab), both need the same edit.

- [ ] **Step 2: Add the "Access" column header (both copies)**

Change both occurrences of:

```python
        self._carrier_table = _make_table(["Material", "Carrier", "System", "Dist (ly)", "Price", "Stock", "Age"])
        ch = self._carrier_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._carrier_table, 1)
```

to:

```python
        self._carrier_table = _make_table(["Material", "Carrier", "System", "Dist (ly)", "Price", "Stock", "Age", "Access"])
        ch = self._carrier_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._carrier_table, 1)
```

(This block is byte-identical at both the Ships tab location, ~lines 315-324, and the Suits & Weapons tab location, ~lines 860-869 — apply the same change to both.)

- [ ] **Step 3: Populate the "Access" column (Ships tab `_refresh_carrier_table`, ~lines 606-681)**

Change:

```python
            age_text, age_sort = _format_age(listing.get("last_updated"), listing.get("last_visited"))
            age_item = _NumericTableWidgetItem(age_text, age_sort)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._carrier_table.setItem(r, 0, mat_item)
            self._carrier_table.setItem(r, 1, name_item)
            self._carrier_table.setItem(r, 2, sys_item)
            self._carrier_table.setItem(r, 3, dist_item)
            self._carrier_table.setItem(r, 4, price_item)
            self._carrier_table.setItem(r, 5, stock_item)
            self._carrier_table.setItem(r, 6, age_item)
        self._carrier_table.setSortingEnabled(True)

        staleness_note = "Carrier listings/locations are crowdsourced from EDDN and can be several days old."
        self._carrier_note.setText(
            staleness_note if rows else
            f"No carriers found selling these materials within {radius:.0f} ly. {staleness_note}"
        )
```

to:

```python
            age_text, age_sort = _format_age(listing.get("last_updated"), listing.get("last_visited"))
            age_item = _NumericTableWidgetItem(age_text, age_sort)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            access_open = listing.get("docking_access") == "all"
            access_item = QTableWidgetItem("Open" if access_open else "Unknown")
            access_item.setForeground(QColor("#6BCB77") if access_open else QColor("#888888"))
            access_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._carrier_table.setItem(r, 0, mat_item)
            self._carrier_table.setItem(r, 1, name_item)
            self._carrier_table.setItem(r, 2, sys_item)
            self._carrier_table.setItem(r, 3, dist_item)
            self._carrier_table.setItem(r, 4, price_item)
            self._carrier_table.setItem(r, 5, stock_item)
            self._carrier_table.setItem(r, 6, age_item)
            self._carrier_table.setItem(r, 7, access_item)
        self._carrier_table.setSortingEnabled(True)

        staleness_note = (
            "Carrier listings/locations are crowdsourced from EDDN and can be several days old. "
            "Carriers with confirmed restricted access are filtered out; \"Unknown\" access is not guaranteed open."
        )
        self._carrier_note.setText(
            staleness_note if rows else
            f"No carriers found selling these materials within {radius:.0f} ly. {staleness_note}"
        )
```

- [ ] **Step 4: Populate the "Access" column (Suits & Weapons tab `_refresh_carrier_table`, ~lines 1118-~1190)**

Apply the identical change from Step 3 to this file's second, near-identical `_refresh_carrier_table` method (its row-building loop and `staleness_note`/`self._carrier_note.setText(...)` block have the same shape as the Ships tab's, just reached via a different method further down the file — re-read this method's current exact text fresh before editing, since despite being structurally identical to the Ships tab version, its surrounding variable names (e.g. `radius`) may differ slightly in this copy).

- [ ] **Step 5: Confirm `QColor` and `QTableWidgetItem` are already imported**

Run: `grep -n "^from PyQt6.QtGui import\|^from PyQt6.QtWidgets import" edc/ui/panels/engineering_panel.py`
Expected: `QColor` appears in the `QtGui` import line and `QTableWidgetItem` in the `QtWidgets` import line (both already used elsewhere in this file per the earlier `grep -n "setForeground|QColor("` results found during design) — no new import needed. If either is missing, add it to the appropriate existing import line.

- [ ] **Step 6: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/engineering_panel.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS (no test exercises this panel directly — this only confirms nothing else broke, e.g. an import error).

- [ ] **Step 8: Manual live verification**

Launch the app, go to the Engineering tab (Ships sub-tab), select a wishlist entry missing at least one material also sold by a known Fleet Carrier. Confirm:
- The "SOLD BY CARRIERS" table has 8 columns, the last labeled "Access".
- Each row shows "Open" (green) or "Unknown" (grey) — no row shows any other text.
- The note beneath the table mentions both crowdsourced staleness and the access-filtering caveat.
- Repeat on the Suits & Weapons sub-tab's equivalent table.
- No crash/traceback in the console.

- [ ] **Step 9: Commit**

```bash
git add edc/ui/panels/engineering_panel.py
git commit -m "feat: show Fleet Carrier docking access on SOLD BY CARRIERS tables"
```
