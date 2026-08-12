# Fleet Carrier Materials Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track other players' Fleet Carrier material sales via EDDN's `fcmaterials_journal/1` schema, and surface a "SOLD BY CARRIERS — CLOSEST FIRST" table in both Engineering panel tabs (Ships and Suits & Weapons) showing nearby carriers selling whatever the selected wishlist item still needs.

**Architecture:** A sixth EDDN buffer in the existing `eddn_market.py`/`eddn_listener.py`/`_EddnFlushWorker` pipeline (mirrors the `commodity/3` path exactly), a new `fleet_carrier_materials` table joined to the existing `station_info` table (for carrier location, since the EDDN schema itself carries none), and a `Repository.search_fleet_carrier_materials()` query reused by both Engineering panel tabs.

**Tech Stack:** Python, PyQt6, SQLite (stdlib `sqlite3` via `Database`/`Repository`), `pyzmq` (already a dependency), `pytest`.

## Global Constraints

- EDDN `fcmaterials_journal/1` messages carry `MarketID`, `CarrierName`, `CarrierID`, `Items` (each `{id, Name, Price, Stock, Demand}`) — verified directly against EDCD/EDDN's schema repo. No system name, no coordinates. `Items[].Name` is always the raw internal material symbol (EDDN strips all `_Localised` fields from this schema).
- Location is resolved via `INNER JOIN station_info ON station_info.market_id = fleet_carrier_materials.market_id` — `station_info.market_id -> system_name` is already populated from `Docked` sightings (the player's own, plus other commanders' via the existing EDDN listener). A carrier with no matching `station_info` row is excluded from search results entirely — never shown with an "unknown location" placeholder.
- All EDDN writes go through the existing background `_EddnFlushWorker` (`edc/ui/main_window.py`), never directly on the main thread — this project already shipped a real UI-freeze fix earlier this session for exactly this failure class (main-thread DB writes during frequent events); the new buffer must follow the identical buffered-then-background-flush pattern as the other five.
- Cutoff on `fleet_carrier_materials.last_updated`: 7 days (tighter than `market_prices`'s existing 30-day cutoff, since carriers restock/relocate far more often than fixed stations). No cutoff filter on `station_info.last_visited` — its age is surfaced to the user as a caveat in the UI instead of silently excluding results.
- Both wishlists (ship Engineering Wishlist and Odyssey Suits & Weapons Wishlist) get cross-referenced against the same `fleet_carrier_materials` table via the same query — material symbols are a shared, non-colliding namespace across both.
- Radius reuses the existing `cfg.market_search_radius_ly` setting — no new config value.
- `EngineeringPanel` currently has no `repo`/`cfg` reference at all (confirmed by reading the file fresh) — its constructor, both tab classes' constructors, and its one instantiation site in `main_window.py` (`main_window.py:1122-1126`) all need updating to thread these through.

---

## File Structure

- **Modify:** `persistence/database.py` — new `fleet_carrier_materials` table via the existing flat migration-list pattern.
- **Modify:** `persistence/repository.py` — `save_fleet_carrier_materials_batch()`, `search_fleet_carrier_materials()`, a new `_fleet_carrier_cutoff()` helper (mirrors the existing `_market_data_cutoff()`).
- **Test:** `tests/test_fleet_carrier_materials.py` — new file, real temp-file SQLite, same fixture pattern as `tests/test_odyssey_farming_candidates.py`.
- **Modify:** `edc/core/eddn_listener.py` — new `_FCMATERIALS_SCHEMA_PREFIX` branch, new `fcmaterials_seen` signal.
- **Modify:** `edc/core/eddn_market.py` — sixth buffer (`_fcmaterials_buffer`), `on_fcmaterials_message()`, folded into `pop_buffers()`/`write_buffers()`/`flush()`/`buffered_counts()`.
- **Modify:** `edc/ui/main_window.py` — connect the new signal, extend `_EddnFlushWorker` to carry the sixth buffer, thread `repo`/`cfg` into `EngineeringPanel`'s constructor call.
- **Modify:** `edc/ui/panels/engineering_panel.py` — both tab classes gain a "SOLD BY CARRIERS — CLOSEST FIRST" table, a `_refresh_carrier_table()` method each, and constructor params for `repo`/`cfg`.

---

### Task 1: Schema + Repository

**Files:**
- Modify: `persistence/database.py`
- Modify: `persistence/repository.py`
- Test: `tests/test_fleet_carrier_materials.py`

**Interfaces:**
- Consumes: existing `station_info` table (`market_id, system_name, station_type, last_visited` — already populated by `save_station_info_batch()`), existing `system_coords` table, existing `Repository._nearby_system_coords(x, y, z, radius_ly)` helper (`persistence/repository.py`, currently around line 1223)
- Produces: `Repository.save_fleet_carrier_materials_batch(records: list[tuple])`, `Repository.search_fleet_carrier_materials(material_symbols: list[str], x: float, y: float, z: float, radius_ly: float, exclude_market_id: Optional[int] = None) -> dict[str, list[dict]]` — Task 2 and Task 3 both call these by exact name

- [ ] **Step 1: Add the new table migration**

In `persistence/database.py`, find `run_migrations()`'s flat list of migration strings (re-read the file fresh — this project's CLAUDE.md flags this kind of frequently-touched file as likely stale). Directly after the existing `market_prices` table's `CREATE TABLE IF NOT EXISTS` entry, add:

```python
"""CREATE TABLE IF NOT EXISTS fleet_carrier_materials (
    market_id       INTEGER NOT NULL,
    material_symbol TEXT    NOT NULL,
    carrier_name    TEXT,
    carrier_id      TEXT,
    price           INTEGER,
    stock           INTEGER,
    demand          INTEGER,
    last_updated    TEXT    NOT NULL,
    PRIMARY KEY (market_id, material_symbol)
)""",
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fleet_carrier_materials.py`:

```python
"""Tests for Repository.save_fleet_carrier_materials_batch() and
search_fleet_carrier_materials() -- real SQLite (temp file), not mocks."""
import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_station(repo, market_id, system_name, station_type="FleetCarrier", last_visited="2026-08-12T00:00:00Z"):
    repo.save_station_info_batch([{
        "market_id": market_id,
        "station_name": "Test Carrier",
        "system_name": system_name,
        "station_type": station_type,
        "pads_small": None,
        "pads_medium": None,
        "pads_large": 1,
        "timestamp": last_visited,
    }])


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_material(repo, market_id, symbol, price=1000, stock=5, demand=0,
                    last_updated="2026-08-12T00:00:00Z", carrier_name="Test Carrier", carrier_id="ABC-123"):
    repo.save_fleet_carrier_materials_batch([
        (market_id, symbol, carrier_name, carrier_id, price, stock, demand, last_updated)
    ])


def test_finds_material_within_radius(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["carrier_name"] == "Test Carrier"
    assert result["graphene"][0]["system_name"] == "Sol"


def test_excludes_material_outside_radius(repo):
    _seed_station(repo, 1001, "Far System")
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_carrier_with_no_station_info_row_is_excluded(repo):
    # No _seed_station() call -- simulates a carrier we've never had a
    # Docked sighting for, so its location is genuinely unknown.
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 2002, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_stale_listing_excluded_past_7_day_cutoff(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", last_updated="2026-07-01T00:00:00Z")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_multiple_symbols_returned_in_one_call(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    _seed_material(repo, 1001, "geneticrepairmeds")

    result = repo.search_fleet_carrier_materials(["graphene", "geneticrepairmeds", "unseen"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert len(result["geneticrepairmeds"]) == 1
    assert result["unseen"] == []


def test_exclude_market_id_skips_current_carrier(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0, exclude_market_id=1001)
    assert result["graphene"] == []


def test_sorted_closest_first(repo):
    _seed_station(repo, 1001, "Near")
    _seed_coords(repo, "Near", 10.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", carrier_name="Near Carrier")

    _seed_station(repo, 1002, "Far")
    _seed_coords(repo, "Far", 40.0, 0.0, 0.0)
    _seed_material(repo, 1002, "graphene", carrier_name="Far Carrier")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert [r["carrier_name"] for r in result["graphene"]] == ["Near Carrier", "Far Carrier"]


def test_upsert_overwrites_previous_listing_for_same_carrier_and_material(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", price=1000, stock=5)
    _seed_material(repo, 1001, "graphene", price=2000, stock=9)

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["price"] == 2000
    assert result["graphene"][0]["stock"] == 9


def test_empty_symbol_list_returns_empty_dict(repo):
    result = repo.search_fleet_carrier_materials([], 0.0, 0.0, 0.0, 50.0)
    assert result == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_fleet_carrier_materials.py -v`
Expected: every test FAILs with `AttributeError: 'Repository' object has no attribute 'save_fleet_carrier_materials_batch'` (or `search_fleet_carrier_materials`).

- [ ] **Step 4: Implement the repository methods**

In `persistence/repository.py`, near the top where `_MARKET_DATA_MAX_AGE_DAYS` and `_market_data_cutoff()` are defined (re-read the file fresh first), add a sibling constant and helper:

```python
_FLEET_CARRIER_MAX_AGE_DAYS = 7


def _fleet_carrier_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_FLEET_CARRIER_MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
```

Then add these two methods to the `Repository` class, placed near `save_market_snapshot_batch()`/`search_market_prices_multi()` (re-read the file fresh to find their current location — was around line 772 and 1300 as of this plan's writing, may have shifted):

```python
    def save_fleet_carrier_materials_batch(self, records: list[tuple]):
        """
        records: [(market_id, material_symbol, carrier_name, carrier_id,
                    price, stock, demand, last_updated), ...]
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO fleet_carrier_materials (
                market_id, material_symbol, carrier_name, carrier_id,
                price, stock, demand, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id, material_symbol) DO UPDATE SET
                carrier_name = excluded.carrier_name,
                carrier_id   = excluded.carrier_id,
                price        = excluded.price,
                stock        = excluded.stock,
                demand       = excluded.demand,
                last_updated = excluded.last_updated
            """,
            records,
        )
        self.db.conn.commit()

    def search_fleet_carrier_materials(
        self, material_symbols: list[str], x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
    ) -> dict[str, list[dict]]:
        """
        For each symbol in material_symbols, the nearby Fleet Carriers
        currently selling it, closest first. A carrier only appears if we
        have a station_info row for its market_id (from a Docked sighting,
        ours or another commander's via EDDN) -- fcmaterials_journal itself
        carries no location, so this INNER JOIN is the only way to place a
        carrier at all; one with no such row is silently excluded, never
        shown with an unknown location.
        """
        if not material_symbols:
            return {}

        coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
        if not coords_by_system:
            return {sym: [] for sym in material_symbols}

        sys_placeholders = ",".join("?" for _ in coords_by_system)
        sym_placeholders = ",".join("?" for _ in material_symbols)
        rows = self.db.conn.execute(
            f"""
            SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
                   fcm.stock, fcm.demand, fcm.last_updated,
                   si.market_id, si.system_name, si.last_visited
            FROM fleet_carrier_materials fcm
            INNER JOIN station_info si ON si.market_id = fcm.market_id
            WHERE fcm.material_symbol IN ({sym_placeholders})
                  AND fcm.last_updated >= ?
                  AND si.system_name IN ({sys_placeholders})
            """,
            (*material_symbols, _fleet_carrier_cutoff(), *coords_by_system.keys()),
        ).fetchall()

        by_symbol: dict[str, list[dict]] = {sym: [] for sym in material_symbols}
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = coords_by_system[r["system_name"]]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist
            by_symbol[r["material_symbol"]].append(rec)

        for sym in by_symbol:
            by_symbol[sym].sort(key=lambda r: r["distance_ly"])
        return by_symbol
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_fleet_carrier_materials.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests pass (73 existing plus the 9 new ones).

- [ ] **Step 7: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_fleet_carrier_materials.py
git commit -m "feat: add fleet_carrier_materials table and search_fleet_carrier_materials()"
```

---

### Task 2: EDDN ingestion

**Files:**
- Modify: `edc/core/eddn_listener.py`
- Modify: `edc/core/eddn_market.py`
- Modify: `edc/ui/main_window.py` (signal wiring + `_EddnFlushWorker` only — NOT the `EngineeringPanel` constructor/UI changes, that's Task 3)

**Interfaces:**
- Consumes: `Repository.save_fleet_carrier_materials_batch()` from Task 1
- Produces: `EddnPowerPlayWorker.fcmaterials_seen` signal (emits `dict` — the raw `fcmaterials_journal` message body), `EddnMarketCache.on_fcmaterials_message(msg: dict)` — Task 3 does not consume these directly (only the search query), but the background flush pipeline must be complete and correct for Task 3's live data to ever appear

- [ ] **Step 1: Add the schema-prefix branch and signal to `eddn_listener.py`**

Re-read `edc/core/eddn_listener.py` fresh. Add a new module-level constant directly after `_COMMODITY_SCHEMA_PREFIX`:

```python
_FCMATERIALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fcmaterials_journal/"
```

Add a new signal to `EddnPowerPlayWorker`, directly after the existing `commodity_seen` signal declaration:

```python
    fcmaterials_seen = pyqtSignal(dict)  # raw fcmaterials_journal/1 message body
```

In `_pump()`, add a new branch directly after the existing `if schema.startswith(_COMMODITY_SCHEMA_PREFIX):` block (before the `if not schema.startswith(_JOURNAL_SCHEMA_PREFIX): continue` line):

```python
            if schema.startswith(_FCMATERIALS_SCHEMA_PREFIX):
                msg = data.get("message")
                if (isinstance(msg, dict) and isinstance(msg.get("MarketID"), int)
                        and isinstance(msg.get("Items"), list)):
                    self.fcmaterials_seen.emit(msg)
                continue
```

- [ ] **Step 2: Add the buffer and handler to `eddn_market.py`**

Re-read `edc/core/eddn_market.py` fresh. Add a new buffer to `EddnMarketCache.__init__`, directly after the existing `_codex_buffer` declaration:

```python
        # Keyed by (market_id, material_symbol) -- Fleet Carrier material
        # listings from fcmaterials_journal/1 sightings, any commander's.
        self._fcmaterials_buffer: Dict[Tuple[int, str], tuple] = {}
```

Add a new handler method, directly after `on_codex_entry_seen()`:

```python
    def on_fcmaterials_message(self, msg: Dict[str, Any]) -> None:
        market_id = msg.get("MarketID")
        if not isinstance(market_id, int):
            return
        carrier_name = msg.get("CarrierName") or ""
        carrier_id = msg.get("CarrierID") or ""
        timestamp = msg.get("timestamp") or datetime.now(timezone.utc).isoformat()

        for item in (msg.get("Items") or []):
            if not isinstance(item, dict):
                continue
            name = item.get("Name")
            if not isinstance(name, str) or not name:
                continue
            key = (market_id, name)
            self._fcmaterials_buffer[key] = (
                market_id, name, carrier_name, carrier_id,
                item.get("Price"), item.get("Stock"), item.get("Demand"),
                timestamp,
            )
```

Update `buffered_counts()` to include the new buffer (widen the return type comment/tuple to 5 elements):

```python
    def buffered_counts(self) -> Tuple[int, int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count, station_count, fcmaterials_count) currently buffered — for status/logging."""
        return (
            len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer),
            len(self._station_buffer), len(self._fcmaterials_buffer),
        )
```

Update `pop_buffers()` to snapshot and clear the new buffer too:

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

Update `flush()`:

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

Update `write_buffers()`'s signature and body — add the new parameter and a new write block, directly after the existing `codex` block:

```python
def write_buffers(repo, coords, market, factions, stations, codex, fcmaterials) -> None:
    """The actual writes — factored out so both the main-thread flush()
    (shutdown) and a background worker (periodic, see main_window.py) can
    use the identical logic against whichever Repository they're given."""
    if coords:
        try:
            repo.save_system_coords_batch(coords)
        except Exception:
            log.exception("Failed to flush system_coords batch")

    if market:
        try:
            repo.save_market_snapshot_batch(market)
        except Exception:
            log.exception("Failed to flush market_prices batch")

    if factions:
        for system_address, (system_name, faction, is_controlling, timestamp) in factions:
            try:
                repo.save_system_name_if_missing(system_address, system_name)
                snapshot_date = (timestamp or "")[:10] or date.today().isoformat()
                repo.save_faction_snapshot(
                    system_address, faction, snapshot_date, is_controlling, timestamp or "", "eddn",
                )
            except Exception:
                log.exception("Failed to flush faction sighting for system_address=%s", system_address)

    if stations:
        try:
            repo.save_station_info_batch(stations)
        except Exception:
            log.exception("Failed to flush station_info batch")

    if codex:
        try:
            repo.save_codex_species_sightings_batch(codex)
        except Exception:
            log.exception("Failed to flush codex_species_sightings batch")

    if fcmaterials:
        try:
            repo.save_fleet_carrier_materials_batch(fcmaterials)
        except Exception:
            log.exception("Failed to flush fleet_carrier_materials batch")
```

- [ ] **Step 3: Wire the signal and extend `_EddnFlushWorker` in `main_window.py`**

Re-read `edc/ui/main_window.py` fresh (flagged frequently-stale by this project's CLAUDE.md — do not trust remembered line numbers). Find `_EddnFlushWorker`'s `__init__`/`run()` (was around line 274-306) and update:

```python
class _EddnFlushWorker(QObject):
    """
    Writes a snapshot of EddnMarketCache's buffered EDDN data (popped by
    the main thread via pop_buffers(), which is cheap) plus a WAL
    checkpoint — both used to run directly on the main thread every 45s
    via QTimer, freezing the UI for however long the batch write took.
    Confirmed live: noticeably worse right after docking at a busy
    station's market, since that's exactly when buffered commodity/
    station/faction data peaks. Opens its own connection per the
    project's cross-thread SQLite rule.
    """
    finished = pyqtSignal()

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

Find `_on_market_flush_tick()` (was around line 3745-3762) and update:

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

Find where the other `self._eddn_worker.*.connect(...)` lines live (was around line 1498-1501) and add, directly after the existing `codex_entry_seen` connection:

```python
        self._eddn_worker.fcmaterials_seen.connect(self.eddn_market_cache.on_fcmaterials_message)
```

- [ ] **Step 4: Byte-compile check**

Run: `python -m py_compile edc/core/eddn_listener.py edc/core/eddn_market.py edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all 82 tests pass (this task adds no new automated tests — the EDDN wiring is verified live against the real relay in Step 6, matching this project's established convention for this exact kind of change, e.g. the original `commodity/3` pipeline).

- [ ] **Step 6: Live EDDN verification**

Run the app (or a minimal standalone script instantiating `EddnPowerPlayWorker` and connecting `fcmaterials_seen` to a print statement) against the real EDDN relay for a few minutes. `fcmaterials_journal` is lower-volume than `commodity/3` — if nothing arrives within ~5 minutes, that's expected for this schema (fewer commanders send it than send ship commodity data) and not a failure; confirm no exceptions/crashes in the listener instead. If any message does arrive, confirm it has the expected shape (`MarketID`, `CarrierName`, `Items`) and that it flows through to a `fleet_carrier_materials` row after the next flush tick.

- [ ] **Step 7: Commit**

```bash
git add edc/core/eddn_listener.py edc/core/eddn_market.py edc/ui/main_window.py
git commit -m "feat: ingest EDDN fcmaterials_journal sightings into fleet_carrier_materials"
```

---

### Task 3: Engineering panel UI

**Files:**
- Modify: `edc/ui/panels/engineering_panel.py`
- Modify: `edc/ui/main_window.py:1122-1126` (`EngineeringPanel` instantiation only)

**Interfaces:**
- Consumes: `Repository.search_fleet_carrier_materials(material_symbols, x, y, z, radius_ly, exclude_market_id=None)` from Task 1 (returns `dict[str, list[dict]]`, each dict shaped `{material_symbol, carrier_name, carrier_id, price, stock, demand, last_updated, market_id, system_name, last_visited, distance_ly}`); `cfg.market_search_radius_ly` (existing config field)
- Produces: nothing consumed by other tasks — this is the final task

- [ ] **Step 1: Thread `repo` and `cfg` into `EngineeringPanel` and both tab constructors**

Re-read `edc/ui/panels/engineering_panel.py` fresh (flagged frequently-stale by this project's CLAUDE.md). Update `EngineeringPanel.__init__`'s signature and body:

```python
    def __init__(
        self,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: EngineeringWishlist,
        odyssey_table: OdysseyEngineeringTable,
        odyssey_wishlist_store: OdysseyWishlist,
        experimental_effects: ExperimentalEffectsTable,
        repo,
        cfg,
        parent=None,
    ):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #1e3a5a; background:#080f18; }"
            "QTabBar::tab { background:#0d1a2a; color:#888888; padding:5px 14px;"
            " border:1px solid #1e3a5a; border-bottom:none; margin-right:2px; }"
            "QTabBar::tab:selected { background:#080f18; color:#FFB347; border-bottom:1px solid #080f18; }"
            "QTabBar::tab:hover { color:#c8c8c8; }"
        )
        root.addWidget(self._tabs)

        self._ship_tab = _ShipEngineeringTab(blueprint_table, wishlist_store, experimental_effects, repo, cfg)
        self._odyssey_tab = _OdysseyEngineeringTab(odyssey_table, blueprint_table, odyssey_wishlist_store, repo, cfg)
        self._tabs.addTab(self._ship_tab, "Ships")
        self._tabs.addTab(self._odyssey_tab, "Suits & Weapons")
```

Update `_ShipEngineeringTab.__init__`'s signature (add `repo, cfg` as new parameters, before `parent=None`) and store them:

```python
    def __init__(
        self,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: EngineeringWishlist,
        experimental_effects: ExperimentalEffectsTable,
        repo,
        cfg,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._store = wishlist_store
        self._effects = experimental_effects
        self._repo = repo
        self._cfg = cfg
        self._wishlist: List[Dict[str, Any]] = self._store.load()
        self._state = None
```

Update `_OdysseyEngineeringTab.__init__` the same way — re-read its current signature fresh (was around line 545-567) and add `repo, cfg` as new parameters before `parent=None`, storing them as `self._repo`/`self._cfg` alongside its existing `self._table = odyssey_table` assignment.

- [ ] **Step 2: Add the "SOLD BY CARRIERS" table to `_ShipEngineeringTab`**

In `_ShipEngineeringTab.__init__`, directly after the existing engineer table's note block (`right.addWidget(self._engineer_note)`, was around line 270) and before the `trade_hdr` block, add:

```python
        carrier_hdr = QLabel("SOLD BY CARRIERS — CLOSEST FIRST")
        carrier_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(carrier_hdr)

        self._carrier_table = _make_table(["Carrier", "System", "Dist (ly)", "Price", "Stock"])
        ch = self._carrier_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._carrier_table, 1)

        self._carrier_note = QLabel("")
        self._carrier_note.setWordWrap(True)
        self._carrier_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._carrier_note)
```

- [ ] **Step 3: Implement `_refresh_carrier_table()` for `_ShipEngineeringTab`**

Add this method directly after `_refresh_engineer_table()` (was around line 448-507):

```python
    def _refresh_carrier_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("")
            return
        entry = self._wishlist[row]
        reqs = self._combined_requirements(entry)
        missing_symbols = [sym for sym, qty in reqs.items() if self._held_count(sym) < qty]
        if not missing_symbols:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("All required materials already held.")
            return

        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        if ref_x is None or ref_y is None or ref_z is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Current position unknown.")
            return

        radius = float(getattr(self._cfg, "market_search_radius_ly", 100) or 100)
        current_market_id = getattr(self._state, "current_market_id", None) if self._state else None
        try:
            by_symbol = self._repo.search_fleet_carrier_materials(
                missing_symbols, ref_x, ref_y, ref_z, radius, exclude_market_id=current_market_id,
            )
        except Exception:
            log.exception("Failed to search fleet carrier materials")
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Carrier search failed — see log.")
            return

        rows = []
        for sym, listings in by_symbol.items():
            mat_name = self._blueprints.material_name(sym)
            for listing in listings:
                rows.append((mat_name, listing))
        rows.sort(key=lambda r: r[1]["distance_ly"])

        self._carrier_table.setRowCount(len(rows))
        for r, (mat_name, listing) in enumerate(rows):
            name_item = QTableWidgetItem(f"{listing['carrier_name']} ({mat_name})")
            sys_item = QTableWidgetItem(listing["system_name"])
            dist_item = QTableWidgetItem(f"{listing['distance_ly']:.1f}")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price = listing.get("price")
            price_item = QTableWidgetItem(f"{price:,}" if isinstance(price, int) else "—")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock = listing.get("stock")
            stock_item = QTableWidgetItem(str(stock) if isinstance(stock, int) else "—")
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._carrier_table.setItem(r, 0, name_item)
            self._carrier_table.setItem(r, 1, sys_item)
            self._carrier_table.setItem(r, 2, dist_item)
            self._carrier_table.setItem(r, 3, price_item)
            self._carrier_table.setItem(r, 4, stock_item)

        self._carrier_note.setText(
            "" if rows else
            f"No carriers found selling these materials within {radius:.0f} ly. "
            "Carrier listings/locations are crowdsourced from EDDN and can be several days old."
        )
```

Add a module-level `log = logging.getLogger(__name__)` check — this file already has one at the top (confirmed: `log = logging.getLogger(__name__)` at line 26), so no new import needed, just use the existing `log`.

Call `self._refresh_carrier_table()` from `_refresh_detail_table()` (was around line 417-446), adding it directly after the existing `self._refresh_engineer_table()` call at the end of that method.

- [ ] **Step 4: Repeat Steps 2-3 for `_OdysseyEngineeringTab`**

Same table/widgets, added directly after that class's existing engineer table's note block (`right.addWidget(self._engineer_note)`, was around line 674) — this is the last widget added to the right column in this class's `__init__`, immediately followed by `root.addLayout(right, 3)` closing the method; insert the new table's widgets between those two lines.

Same `_refresh_carrier_table()` method, adapted to this class's requirements source: use `self._requirements_for(entry)` (this class's existing method, was around line 710-720) instead of `_combined_requirements()`, and `self._material_name(sym)` (was around line 706-708, already fixed earlier this session to fall back through `self._table.material_display_name()`) instead of `self._blueprints.material_name(sym)`. Call `self._refresh_carrier_table()` from this class's `_refresh_detail_table()` (was around line 779-800), directly after its existing `self._refresh_engineer_table()` call.

- [ ] **Step 5: Update `main_window.py`'s `EngineeringPanel` instantiation**

Re-read `edc/ui/main_window.py` fresh. Find the `EngineeringPanel(...)` call (was around line 1122-1126) and add `self.repo, self.cfg` to the argument list:

```python
        self.engineering_panel = EngineeringPanel(
            self.engineering_blueprints, self.engineering_wishlist_store,
            self.odyssey_engineering, self.odyssey_wishlist_store,
            self.experimental_effects, self.repo, self.cfg,
        )
```

Confirm `self.repo` and `self.cfg` are both already assigned earlier in `main_window.py`'s `__init__` than this line (they should be — `self.repo` is already used two lines later for `MiningPanel(self.repo)`, and `self.cfg` is used extensively throughout this file). If either isn't yet assigned at this point, move the `EngineeringPanel` instantiation later in `__init__` rather than moving `self.repo`/`self.cfg`'s assignment earlier.

- [ ] **Step 6: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/engineering_panel.py edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests still pass (this task adds no new automated tests — UI wiring is verified visually per this project's convention).

- [ ] **Step 8: Visual verification**

Launch the app, open the Engineering tab. On both the Ships and Suits & Weapons sub-tabs:
- Select a wishlist item with at least one missing material — confirm the new "SOLD BY CARRIERS — CLOSEST FIRST" table renders below the existing engineer table without layout breakage.
- With no live carrier data yet (expected, since `fcmaterials_journal` is low-volume — see Task 2 Step 6), confirm the empty-state note renders sensibly rather than an exception or a blank crash.
- Select a wishlist item with zero missing materials — confirm the "All required materials already held" note renders and the table clears.

- [ ] **Step 9: Commit**

```bash
git add edc/ui/panels/engineering_panel.py edc/ui/main_window.py
git commit -m "feat: add Fleet Carrier materials table to Engineering panel"
```
