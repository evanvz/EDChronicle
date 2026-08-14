# Footfall Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track whether *any* commander has ever footfalled on a body (via the real `WasFootfalled` Scan-event field), fix a data-loss bug where a body's own personal footfall record gets wiped on re-scan, and surface both correctly as a new "Already Footfalled" badge distinct from the existing personal-achievement badges.

**Architecture:** Mirrors the `was_mapped`/`dss_mapped` pattern already established in this codebase end to end: a new `was_footfalled` column on the persisted `bodies` table, read by the historical journal importer and the live Scan handler, rehydrated into `state.bodies` on system entry, and rendered as a badge.

**Tech Stack:** Python, PyQt6, SQLite.

## Global Constraints

- `was_footfalled` always reflects the latest scan's server truth — plain overwrite on conflict, like `was_mapped`/`dss_mapped`, not a `COALESCE`-guarded field.
- The live Scan handler (`edc/engine/handlers/exploration.py`) must preserve `HasFootfall`/`FirstFootfall` across re-scans via `existing.get(...)` — these two are ONLY ever set by `Disembark` handling elsewhere (untouched, out of scope), never by a Scan event itself. This fixes the data-loss bug where a re-scan of an already-footfalled body wiped its personal footfall record.
- `edc/core/event_engine.py`'s inline Scan/Disembark handling is NOT touched — confirmed dead/superseded by `exploration.handle()` for anything both cover, explicitly out of scope (see `docs/superpowers/specs/2026-08-14-footfall-tracking-design.md`'s "Known duplicate-code issue").
- Bumping the DB schema version is required for the persisted historical data to actually backfill on existing installs — `_REQUIRED_SCHEMA_VERSION` in `persistence/database.py` must go from 5 to 6 (this constant forces a full journal re-import when incremented; without it, only journal files written after this update would ever get `was_footfalled` recorded).
- No schema changes beyond the one new column. No new files except test files.

---

## File Structure

- **Modify:** `persistence/database.py` — new migration, schema version bump.
- **Modify:** `persistence/repository.py` — `save_body()`/`get_bodies()` extended.
- **Modify:** `edc/core/journal_importer.py` — `CachedBody` gains a field, `_handle_scan`/`_handle_saa_scan_complete` thread it through.
- **Modify:** `edc/engine/handlers/exploration.py` — Scan handler rec construction.
- **Modify:** `edc/ui/system_data_loader.py` — rehydration.
- **Modify:** `edc/ui/panels/exploration_panel.py` — badge rendering.
- **Test:** `tests/test_footfall_tracking.py` (new).

---

### Task 1: Persistence — schema, `save_body()`, `get_bodies()`

**Files:**
- Modify: `persistence/database.py`
- Modify: `persistence/repository.py`
- Test: `tests/test_footfall_tracking.py`

**Interfaces:**
- Produces: `Repository.save_body(..., was_footfalled: int = 0)` and `Repository.get_bodies(system_address)` rows carrying `was_footfalled` — consumed by Task 2 (journal importer) and Task 4 (rehydration).

- [ ] **Step 1: Write the failing test**

Create `tests/test_footfall_tracking.py`:

```python
"""Tests for was_footfalled tracking -- persistence round-trip, the
journal importer's parsing, and the live Scan handler's data-loss fix.
Real SQLite (temp file) and real EventEngine, not mocks, matching this
repo's established convention."""
from pathlib import Path

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


def test_save_body_persists_was_footfalled(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=1,
    )
    rows = list(repo.get_bodies(1))
    assert len(rows) == 1
    assert rows[0]["was_footfalled"] == 1


def test_save_body_was_footfalled_defaults_to_zero(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
    )
    rows = list(repo.get_bodies(1))
    assert rows[0]["was_footfalled"] == 0


def test_save_body_was_footfalled_overwrites_on_conflict(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=1,
    )
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=0,
    )
    rows = list(repo.get_bodies(1))
    assert rows[0]["was_footfalled"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: all 3 tests FAIL with `TypeError: save_body() got an unexpected keyword argument 'was_footfalled'`.

- [ ] **Step 3: Add the migration and bump the schema version**

Re-read `persistence/database.py` fresh before editing (confirm the migrations list and `_REQUIRED_SCHEMA_VERSION` are still as read immediately before this plan was written). Current code (end of the migrations list):

```python
            """CREATE TABLE IF NOT EXISTS colonisation_depots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id      INTEGER,
                system_address INTEGER,
                system_name    TEXT NOT NULL,
                station_name   TEXT NOT NULL,
                progress       REAL,
                complete       INTEGER DEFAULT 0,
                resources      TEXT,
                last_updated   TEXT
            )""",
        ]
```

Replace with (adds the new migration as the last entry):

```python
            """CREATE TABLE IF NOT EXISTS colonisation_depots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id      INTEGER,
                system_address INTEGER,
                system_name    TEXT NOT NULL,
                station_name   TEXT NOT NULL,
                progress       REAL,
                complete       INTEGER DEFAULT 0,
                resources      TEXT,
                last_updated   TEXT
            )""",
            "ALTER TABLE bodies ADD COLUMN was_footfalled INTEGER DEFAULT 0",
        ]
```

Current code:

```python
    # Bump this constant whenever a migration requires journals to be re-imported.
    _REQUIRED_SCHEMA_VERSION = 5
```

Replace with:

```python
    # Bump this constant whenever a migration requires journals to be re-imported.
    _REQUIRED_SCHEMA_VERSION = 6
```

And update the version-history comment block right below it — current code:

```python
            # v2: body physical-stat columns were added.
            # v3: station_info (landing pad ground truth from Docked events) was added.
            # v4: station_info.station_services/station_faction (Interstellar Factors detection) was added.
            # v5: rings table (hotspot scan history) was added.
            # Re-import all journals to backfill.
```

Replace with:

```python
            # v2: body physical-stat columns were added.
            # v3: station_info (landing pad ground truth from Docked events) was added.
            # v4: station_info.station_services/station_faction (Interstellar Factors detection) was added.
            # v5: rings table (hotspot scan history) was added.
            # v6: bodies.was_footfalled was added.
            # Re-import all journals to backfill.
```

- [ ] **Step 4: Extend `save_body()` and `get_bodies()`**

Re-read `persistence/repository.py` fresh before editing. Current `save_body()`:

```python
    def save_body(
        self,
        system_address: int,
        body_id: int,
        body_name: str,
        planet_class: str,
        terraformable: int,
        landable,
        was_mapped: int,
        dss_mapped: int,
        estimated_value,
        distance_ls,
        volcanism: str = None,
        materials: str = None,
        mass_em=None,
        radius=None,
        surface_gravity=None,
        surface_temperature=None,
        surface_pressure=None,
        atmosphere_type: str = None,
        atmosphere: str = None,
        atmosphere_composition: str = None,
        composition: str = None,
        tidal_lock=None,
        first_discovered=None,
        first_mapped=None,
    ):
        self.db.execute(
            """
            INSERT INTO bodies (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                body_name               = excluded.body_name,
                planet_class            = excluded.planet_class,
                terraformable           = excluded.terraformable,
                landable                = excluded.landable,
                was_mapped              = excluded.was_mapped,
                dss_mapped              = excluded.dss_mapped,
                estimated_value         = excluded.estimated_value,
                distance_ls             = excluded.distance_ls,
                volcanism               = COALESCE(excluded.volcanism, bodies.volcanism),
                materials               = COALESCE(excluded.materials, bodies.materials),
                mass_em                 = COALESCE(excluded.mass_em, bodies.mass_em),
                radius                  = COALESCE(excluded.radius, bodies.radius),
                surface_gravity         = COALESCE(excluded.surface_gravity, bodies.surface_gravity),
                surface_temperature     = COALESCE(excluded.surface_temperature, bodies.surface_temperature),
                surface_pressure        = COALESCE(excluded.surface_pressure, bodies.surface_pressure),
                atmosphere_type         = COALESCE(excluded.atmosphere_type, bodies.atmosphere_type),
                atmosphere              = COALESCE(excluded.atmosphere, bodies.atmosphere),
                atmosphere_composition  = COALESCE(excluded.atmosphere_composition, bodies.atmosphere_composition),
                composition             = COALESCE(excluded.composition, bodies.composition),
                tidal_lock              = COALESCE(excluded.tidal_lock, bodies.tidal_lock),
                first_discovered        = COALESCE(excluded.first_discovered, bodies.first_discovered),
                first_mapped            = COALESCE(excluded.first_mapped, bodies.first_mapped)
            """,
            (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped,
            ),
        )
```

Replace with (adds `was_footfalled: int = 0` as a new keyword parameter with a default, so all three existing call sites in `journal_importer.py` keep working before Task 2 updates them; included in INSERT/VALUES/ON CONFLICT as a plain overwrite):

```python
    def save_body(
        self,
        system_address: int,
        body_id: int,
        body_name: str,
        planet_class: str,
        terraformable: int,
        landable,
        was_mapped: int,
        dss_mapped: int,
        estimated_value,
        distance_ls,
        volcanism: str = None,
        materials: str = None,
        mass_em=None,
        radius=None,
        surface_gravity=None,
        surface_temperature=None,
        surface_pressure=None,
        atmosphere_type: str = None,
        atmosphere: str = None,
        atmosphere_composition: str = None,
        composition: str = None,
        tidal_lock=None,
        first_discovered=None,
        first_mapped=None,
        was_footfalled: int = 0,
    ):
        self.db.execute(
            """
            INSERT INTO bodies (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped, was_footfalled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                body_name               = excluded.body_name,
                planet_class            = excluded.planet_class,
                terraformable           = excluded.terraformable,
                landable                = excluded.landable,
                was_mapped              = excluded.was_mapped,
                dss_mapped              = excluded.dss_mapped,
                estimated_value         = excluded.estimated_value,
                distance_ls             = excluded.distance_ls,
                volcanism               = COALESCE(excluded.volcanism, bodies.volcanism),
                materials               = COALESCE(excluded.materials, bodies.materials),
                mass_em                 = COALESCE(excluded.mass_em, bodies.mass_em),
                radius                  = COALESCE(excluded.radius, bodies.radius),
                surface_gravity         = COALESCE(excluded.surface_gravity, bodies.surface_gravity),
                surface_temperature     = COALESCE(excluded.surface_temperature, bodies.surface_temperature),
                surface_pressure        = COALESCE(excluded.surface_pressure, bodies.surface_pressure),
                atmosphere_type         = COALESCE(excluded.atmosphere_type, bodies.atmosphere_type),
                atmosphere              = COALESCE(excluded.atmosphere, bodies.atmosphere),
                atmosphere_composition  = COALESCE(excluded.atmosphere_composition, bodies.atmosphere_composition),
                composition             = COALESCE(excluded.composition, bodies.composition),
                tidal_lock              = COALESCE(excluded.tidal_lock, bodies.tidal_lock),
                first_discovered        = COALESCE(excluded.first_discovered, bodies.first_discovered),
                first_mapped            = COALESCE(excluded.first_mapped, bodies.first_mapped),
                was_footfalled          = excluded.was_footfalled
            """,
            (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped, was_footfalled,
            ),
        )
```

Current `get_bodies()`:

```python
    def get_bodies(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_id,
                body_name,
                planet_class,
                terraformable,
                landable,
                was_mapped,
                dss_mapped,
                estimated_value,
                distance_ls,
                volcanism,
                materials,
                first_footfall,
                has_footfall,
                mass_em,
                radius,
                surface_gravity,
                surface_temperature,
                surface_pressure,
                atmosphere_type,
                atmosphere,
                atmosphere_composition,
                composition,
                tidal_lock,
                first_discovered,
                first_mapped
            FROM bodies
            WHERE system_address = ?
```

Replace with (adds `was_footfalled` to the SELECT list, next to `dss_mapped` for readability):

```python
    def get_bodies(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_id,
                body_name,
                planet_class,
                terraformable,
                landable,
                was_mapped,
                dss_mapped,
                was_footfalled,
                estimated_value,
                distance_ls,
                volcanism,
                materials,
                first_footfall,
                has_footfall,
                mass_em,
                radius,
                surface_gravity,
                surface_temperature,
                surface_pressure,
                atmosphere_type,
                atmosphere,
                atmosphere_composition,
                composition,
                tidal_lock,
                first_discovered,
                first_mapped
            FROM bodies
            WHERE system_address = ?
```

(Only the `WHERE`-clause line and everything after it, unchanged, continues below — do not modify anything past `WHERE system_address = ?` in this step.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all previously-passing tests plus these 3 new ones pass — no regressions (confirm nothing else calls `save_body()` positionally in a way the new keyword-only-with-default parameter would break; it's appended at the end with a default, so existing positional/keyword calls are unaffected).

- [ ] **Step 7: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_footfall_tracking.py
git commit -m "feat: add was_footfalled column, thread through save_body/get_bodies"
```

---

### Task 2: Historical import — `journal_importer.py`

**Files:**
- Modify: `edc/core/journal_importer.py`
- Test: `tests/test_footfall_tracking.py`

**Interfaces:**
- Consumes: `Repository.save_body(..., was_footfalled: int = 0)` (Task 1).
- Produces: nothing consumed by later tasks — this task is a leaf in the dependency graph, safe to develop in parallel conceptually, but still sequenced after Task 1 since it calls `save_body()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_footfall_tracking.py`:

```python
from edc.core.journal_importer import JournalImporter


def test_importer_parses_was_footfalled_from_scan(repo, tmp_path):
    importer = JournalImporter(tmp_path, repo)
    importer.current_system_address = 5
    event = {
        "event": "Scan", "ScanType": "Detailed", "BodyName": "Test Body 1",
        "BodyID": 1, "SystemAddress": 5, "PlanetClass": "Rocky body",
        "TerraformState": "", "WasMapped": False, "WasFootfalled": True,
        "WasDiscovered": True, "DistanceFromArrivalLS": 100.0,
    }
    importer._process_event(event)
    rows = list(repo.get_bodies(5))
    assert rows[0]["was_footfalled"] == 1


def test_importer_was_footfalled_survives_saa_scan_complete(repo, tmp_path):
    # The real scenario this test guards: a body scanned with
    # WasFootfalled=true, then later DSS-mapped in the same import pass --
    # the SAAScanComplete call site must not reset was_footfalled to 0.
    importer = JournalImporter(tmp_path, repo)
    importer.current_system_address = 5
    scan_event = {
        "event": "Scan", "ScanType": "Detailed", "BodyName": "Test Body 1",
        "BodyID": 1, "SystemAddress": 5, "PlanetClass": "Rocky body",
        "TerraformState": "", "WasMapped": False, "WasFootfalled": True,
        "WasDiscovered": True, "DistanceFromArrivalLS": 100.0,
    }
    importer._process_event(scan_event)
    saa_event = {
        "event": "SAAScanComplete", "BodyName": "Test Body 1", "BodyID": 1,
        "SystemAddress": 5, "ProbesUsed": 5, "EfficiencyTarget": 6,
    }
    importer._process_event(saa_event)
    rows = list(repo.get_bodies(5))
    assert rows[0]["was_footfalled"] == 1
    assert rows[0]["dss_mapped"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: both new tests FAIL — `test_importer_parses_was_footfalled_from_scan` because `was_footfalled` isn't read from the event at all yet (asserts `1`, gets `0`, the `save_body()` call default); `test_importer_was_footfalled_survives_saa_scan_complete` fails the same way.

- [ ] **Step 3: Add `was_footfalled` to `CachedBody`**

Re-read `edc/core/journal_importer.py` fresh before editing (confirm the `CachedBody` dataclass and both `_handle_scan`/`_handle_saa_scan_complete` still match — re-read immediately before this plan was written). Current code:

```python
class CachedBody:
    body_id: int
    body_name: str
    planet_class: str | None = None
    terraformable: int | None = 0
    landable: int | None = None
    was_mapped: int | None = 0
    dss_mapped: int | None = 0
    estimated_value: int | None = None
    distance_ls: float | None = None
```

Replace with:

```python
class CachedBody:
    body_id: int
    body_name: str
    planet_class: str | None = None
    terraformable: int | None = 0
    landable: int | None = None
    was_mapped: int | None = 0
    dss_mapped: int | None = 0
    estimated_value: int | None = None
    distance_ls: float | None = None
    was_footfalled: int | None = 0
```

- [ ] **Step 4: Parse `WasFootfalled` in `_handle_scan`, thread through both call sites**

Current code (the `was_mapped` line near the top of `_handle_scan`):

```python
        was_mapped = int(bool(event.get("WasMapped", False)))
        distance_ls = event.get("DistanceFromArrivalLS")
```

Replace with:

```python
        was_mapped = int(bool(event.get("WasMapped", False)))
        was_footfalled = int(bool(event.get("WasFootfalled", False)))
        distance_ls = event.get("DistanceFromArrivalLS")
```

Current code (the direct `save_body()` call inside `_handle_scan`):

```python
        self.repo.save_body(
            system_address=system_address,
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
            volcanism=volcanism_raw,
            materials=materials_json,
```

Replace with (adds `was_footfalled=was_footfalled` right after `was_mapped=was_mapped` — do not alter any of the other parameters on the lines below `materials=materials_json` that this excerpt cuts off at):

```python
        self.repo.save_body(
            system_address=system_address,
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            was_footfalled=was_footfalled,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
            volcanism=volcanism_raw,
            materials=materials_json,
```

Current code (the `CachedBody(...)` construction at the end of `_handle_scan`):

```python
        self.bodies_by_name[body_name] = CachedBody(
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
        )
```

Replace with:

```python
        self.bodies_by_name[body_name] = CachedBody(
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
            was_footfalled=was_footfalled,
        )
```

- [ ] **Step 5: Thread `cached.was_footfalled` through `_handle_saa_scan_complete`**

Current code:

```python
        self.repo.save_body(
            system_address=system_address,
            body_id=cached.body_id,
            body_name=cached.body_name,
            planet_class=cached.planet_class,
            terraformable=cached.terraformable,
            landable=cached.landable,
            was_mapped=cached.was_mapped,
            dss_mapped=cached.dss_mapped,
            estimated_value=cached.estimated_value,
            distance_ls=cached.distance_ls,
            first_mapped=first_mapped,
        )
```

Replace with:

```python
        self.repo.save_body(
            system_address=system_address,
            body_id=cached.body_id,
            body_name=cached.body_name,
            planet_class=cached.planet_class,
            terraformable=cached.terraformable,
            landable=cached.landable,
            was_mapped=cached.was_mapped,
            dss_mapped=cached.dss_mapped,
            estimated_value=cached.estimated_value,
            distance_ls=cached.distance_ls,
            first_mapped=first_mapped,
            was_footfalled=cached.was_footfalled,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: all 5 tests so far PASS.

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add edc/core/journal_importer.py tests/test_footfall_tracking.py
git commit -m "feat: parse WasFootfalled in the historical journal importer"
```

---

### Task 3: Live tracking — `edc/engine/handlers/exploration.py`

**Files:**
- Modify: `edc/engine/handlers/exploration.py`
- Test: `tests/test_footfall_tracking.py`

**Interfaces:**
- Produces: `state.bodies[name]["WasFootfalled"]`, and `HasFootfall`/`FirstFootfall` now survive across re-scans — consumed by Task 4 (badge rendering).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_footfall_tracking.py`:

```python
from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.engine.handlers import exploration


@pytest.fixture
def engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _scan_event(was_footfalled=False):
    return {
        "event": "Scan", "ScanType": "Detailed", "BodyName": "Test Body 1",
        "BodyID": 1, "SystemAddress": 5, "PlanetClass": "Rocky body",
        "TerraformState": "", "WasMapped": False, "WasFootfalled": was_footfalled,
        "WasDiscovered": True, "DistanceFromArrivalLS": 100.0,
    }


def test_scan_handler_reads_was_footfalled(engine):
    exploration.handle(engine, "Scan", _scan_event(was_footfalled=True), [])
    assert engine.state.bodies["Test Body 1"]["WasFootfalled"] is True


def test_scan_handler_preserves_personal_footfall_across_rescan(engine):
    # The actual data-loss repro this task fixes: simulate a prior
    # Disembark having already set HasFootfall/FirstFootfall (the only
    # real way these get set live), then confirm a later Scan of the same
    # body doesn't wipe them.
    exploration.handle(engine, "Scan", _scan_event(), [])
    engine.state.bodies["Test Body 1"]["HasFootfall"] = True
    engine.state.bodies["Test Body 1"]["FirstFootfall"] = True

    exploration.handle(engine, "Scan", _scan_event(), [])

    assert engine.state.bodies["Test Body 1"]["HasFootfall"] is True
    assert engine.state.bodies["Test Body 1"]["FirstFootfall"] is True


def test_scan_handler_body_never_footfalled_stays_false(engine):
    exploration.handle(engine, "Scan", _scan_event(), [])
    assert engine.state.bodies["Test Body 1"]["HasFootfall"] is False
    assert engine.state.bodies["Test Body 1"]["FirstFootfall"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: `test_scan_handler_reads_was_footfalled` FAILs with `KeyError: 'WasFootfalled'`; `test_scan_handler_preserves_personal_footfall_across_rescan` FAILs — the second `exploration.handle()` call currently rebuilds `rec` without carrying `HasFootfall`/`FirstFootfall` forward, so they'd be absent (`KeyError` or `False` via `.get()`, depending on how the assertion is written — either way, not `True`); `test_scan_handler_body_never_footfalled_stays_false` may already incidentally pass or fail with `KeyError` depending on current dict shape — run it to see, but do not treat this one as evidence either way until Step 4 lands.

- [ ] **Step 3: Add the three new keys to the Scan handler's `rec` construction**

Re-read `edc/engine/handlers/exploration.py` fresh before editing (confirm the current `rec = {...}` block still matches — this exact code was touched once already today by an earlier fix in this session, commit `601ec31`; re-read rather than assume). Current code:

```python
            rec = {
                "BodyID":          body_id if isinstance(body_id, int) else existing.get("BodyID"),
                "BodyName":        body_name,
                "PlanetClass":     planet_class,
                "Terraformable":   terraformable,
                "DistanceLS":      distance,
                "Landable":        landable,
                "WasMapped":       was_mapped,
                "DSSMapped":       dss_mapped or existing.get("DSSMapped", False),
                "FirstDiscovered": first_discovered,
                "EstimatedValue":  estimated_value,
                "BioSignals":      existing.get("BioSignals", 0),
                "GeoSignals":      existing.get("GeoSignals", 0),
                "HumanSignals":    existing.get("HumanSignals", 0),
                "BioGenuses":      existing.get("BioGenuses", []),
                "Materials":       mats_dict,
                "Volcanism":       volcanism,
            }
            engine.state.bodies[body_name] = rec
```

Replace with (adds `WasFootfalled` read fresh from the event, and `HasFootfall`/`FirstFootfall` preserved from `existing` — these two are never set from a Scan event itself, only from `Disembark` handling elsewhere, untouched by this plan):

```python
            rec = {
                "BodyID":          body_id if isinstance(body_id, int) else existing.get("BodyID"),
                "BodyName":        body_name,
                "PlanetClass":     planet_class,
                "Terraformable":   terraformable,
                "DistanceLS":      distance,
                "Landable":        landable,
                "WasMapped":       was_mapped,
                "DSSMapped":       dss_mapped or existing.get("DSSMapped", False),
                "WasFootfalled":   bool(event.get("WasFootfalled", False)),
                "HasFootfall":     existing.get("HasFootfall", False),
                "FirstFootfall":   existing.get("FirstFootfall", False),
                "FirstDiscovered": first_discovered,
                "EstimatedValue":  estimated_value,
                "BioSignals":      existing.get("BioSignals", 0),
                "GeoSignals":      existing.get("GeoSignals", 0),
                "HumanSignals":    existing.get("HumanSignals", 0),
                "BioGenuses":      existing.get("BioGenuses", []),
                "Materials":       mats_dict,
                "Volcanism":       volcanism,
            }
            engine.state.bodies[body_name] = rec
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_footfall_tracking.py -v`
Expected: all 8 tests so far PASS.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Byte-compile check**

Run: `python -m py_compile edc/engine/handlers/exploration.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add edc/engine/handlers/exploration.py tests/test_footfall_tracking.py
git commit -m "fix: read WasFootfalled live, preserve personal footfall record across re-scans"
```

---

### Task 4: Rehydration + badge — `system_data_loader.py`, `exploration_panel.py`

**Files:**
- Modify: `edc/ui/system_data_loader.py`
- Modify: `edc/ui/panels/exploration_panel.py`

**Interfaces:**
- Consumes: `Repository.get_bodies()` rows carrying `was_footfalled` (Task 1), `state.bodies[name]["WasFootfalled"]` (Task 3).
- Produces: nothing consumed elsewhere — final task in this plan.

- [ ] **Step 1: Rehydrate `WasFootfalled` from the persisted row**

Re-read `edc/ui/system_data_loader.py` fresh before editing (confirm the `rec = {...}` block still matches). Current code:

```python
            rec = {
                "BodyID": body_id if isinstance(body_id, int) else None,
                "BodyName": body_name,
                "PlanetClass": row["planet_class"] or "",
                "Terraformable": bool(row["terraformable"]),
                "DistanceLS": row["distance_ls"],
                "Landable": None if row["landable"] is None else bool(row["landable"]),
                "WasMapped":      bool(row["was_mapped"]),
                "DSSMapped":      bool(row["dss_mapped"]),
                "EstimatedValue": estimated_value,
```

Replace with (adds `WasFootfalled` right after `DSSMapped`, matching the guarded-lookup style already used a few lines below for `first_footfall`/`has_footfall` since this row-dict may come from a DB that hasn't run the new migration yet in a rare edge case):

```python
            rec = {
                "BodyID": body_id if isinstance(body_id, int) else None,
                "BodyName": body_name,
                "PlanetClass": row["planet_class"] or "",
                "Terraformable": bool(row["terraformable"]),
                "DistanceLS": row["distance_ls"],
                "Landable": None if row["landable"] is None else bool(row["landable"]),
                "WasMapped":      bool(row["was_mapped"]),
                "DSSMapped":      bool(row["dss_mapped"]),
                "WasFootfalled":  bool(row["was_footfalled"]) if "was_footfalled" in row.keys() else False,
                "EstimatedValue": estimated_value,
```

- [ ] **Step 2: Read the new local in the per-body loop**

Re-read `edc/ui/panels/exploration_panel.py` fresh before editing (confirm the current line numbers and exact code — this file was touched once already today, commit `13a93a5`). Current code:

```python
            first_footfall = bool(rec.get("FirstFootfall", False))
            has_footfall   = bool(rec.get("HasFootfall", False))
```

Replace with:

```python
            first_footfall = bool(rec.get("FirstFootfall", False))
            has_footfall   = bool(rec.get("HasFootfall", False))
            was_footfalled = bool(rec.get("WasFootfalled", False))
```

- [ ] **Step 3: Add the new badge**

Confirm the current badge-building section still matches (re-read fresh, find `first_footfall`/`has_footfall` in the badges list this same function builds later — the two reads above and this badge block are in the same function but the badge block is further down, near the other `_badge(...)` calls). Current code:

```python
        if first_footfall:
            badges.append(self._badge("First Footfall", "#2a1500", "#FFD700", bold=True))
        elif has_footfall:
            badges.append(self._badge("Footfall", "#1a1a1a", "#AAAAAA"))
```

Replace with (a third `elif` continuing the same chain, so it only fires when the player hasn't personally footfalled there — a muted teal, distinct from every other badge color already used in this function: green Landable, purple Terraformable, orange First Discovery, blue DSS Mapped, grey Prev Mapped, gold First Footfall, grey Footfall):

```python
        if first_footfall:
            badges.append(self._badge("First Footfall", "#2a1500", "#FFD700", bold=True))
        elif has_footfall:
            badges.append(self._badge("Footfall", "#1a1a1a", "#AAAAAA"))
        elif was_footfalled:
            badges.append(self._badge("Already Footfalled", "#0a2a2a", "#5FB3B3"))
```

- [ ] **Step 4: Byte-compile check**

Run: `python -m py_compile edc/ui/system_data_loader.py edc/ui/panels/exploration_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass (this task adds no new automated tests — rendering/rehydration only, verified visually per this file's established convention from earlier plans today).

- [ ] **Step 6: Headless verification**

Write a scratch script (in this project's scratchpad, not committed) that constructs a real `Repository` against a `tmp_path` SQLite DB, calls `save_body(..., was_footfalled=1)` for a test body with no `has_footfall`/`first_footfall`, then constructs a minimal object exposing `.repo`/`.state`/`.planet_values` matching what `system_data_loader.py`'s rehydration function expects (check its actual current signature/class before writing this), calls the rehydration function, and confirms `state.bodies["Test Body"]["WasFootfalled"] is True`. Report the actual output.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/system_data_loader.py edc/ui/panels/exploration_panel.py
git commit -m "feat: rehydrate WasFootfalled and show an Already Footfalled badge"
```
