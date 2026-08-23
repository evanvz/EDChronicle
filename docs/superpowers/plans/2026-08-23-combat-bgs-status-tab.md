# Combat BGS/System Status Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "System Status" sub-tab under Combat showing War/CivilWar
conflicts, multi-state factions, and RES/Low/High/Hazardous RES presence
for every tracked system within a configurable radius of the player's
current location, sourced from both the player's own journal and EDDN.

**Architecture:** Two new "latest-known-per-system" tables
(`system_bgs_status`, `system_res_sites`), fed by two parallel pipelines
that already exist for other data (own-journal live dispatch in
`main_window.py`; EDDN's existing always-on ZMQ listener gaining two new
signals off schemas it already receives). A new self-contained radius-
search panel (same shape as `market_panel.py`) renders the merged result;
`combat_panel.py`'s existing flat content becomes one tab of a new inner
`QTabWidget`, with the new panel as the second.

**Tech Stack:** Python, PyQt6, SQLite (stdlib `sqlite3`), ZeroMQ (`zmq`,
already a dependency via `eddn_listener.py`).

**Spec:** `docs/superpowers/specs/2026-08-23-combat-bgs-status-tab-design.md`

## Global Constraints

- Freshness-guarded upsert (`ON CONFLICT ... WHERE excluded.data_timestamp
  >= <table>.data_timestamp`) on both new tables — same idiom as
  `save_faction_snapshot`, so whichever pipeline has the most recent
  underlying data wins regardless of write order.
- Both new tables are written to going forward only — never backfilled
  from old journal files (stale war/RES data would be actively
  misleading). No `_REQUIRED_SCHEMA_VERSION` bump.
- Search results older than 14 days (`_MARKET_DATA_MAX_AGE_DAYS`, already
  defined in `persistence/repository.py:14`) are excluded, reusing the
  existing constant rather than inventing a new one.
- A row is only ever written when there's something combat/BGS-relevant
  to show: `system_bgs_status` needs a War/CivilWar conflict or a faction
  with a non-empty active/pending/recovering state; `system_res_sites`
  needs at least one RES tier.
- All new SQLite access from a background thread opens its own
  `Database`/`Repository` instance (project-wide rule — connections
  cannot be shared across threads).

---

### Task 1: Shared RES-tier parsing helper

**Files:**
- Create: `edc/core/res_signals.py`
- Test: `tests/test_res_signals.py`

**Interfaces:**
- Produces: `res_tier_from_signal_name(signal_name: str) -> str`, used by
  Task 4 (own journal) and Task 6 (EDDN).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for res_tier_from_signal_name() -- pure function, no Qt needed."""
from edc.core.res_signals import res_tier_from_signal_name


def test_nominal_res_has_no_bracket():
    assert res_tier_from_signal_name("Resource Extraction Site") == "Nominal"


def test_low_res():
    assert res_tier_from_signal_name("Resource Extraction Site [Low]") == "Low"


def test_high_res():
    assert res_tier_from_signal_name("Resource Extraction Site [High]") == "High"


def test_hazardous_res():
    assert res_tier_from_signal_name("Resource Extraction Site [Hazardous]") == "Hazardous"


def test_non_res_signal_name_defaults_nominal():
    assert res_tier_from_signal_name("Nav Beacon") == "Nominal"


def test_non_string_input_defaults_nominal():
    assert res_tier_from_signal_name(None) == "Nominal"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_res_signals.py -v`
Expected: FAIL with "No module named 'edc.core.res_signals'"

- [ ] **Step 3: Write the implementation**

```python
"""Shared RES-tier parsing for FSSSignalDiscovered's ResourceExtraction
signals -- used by both the live event engine (own journal, event_engine.py)
and eddn_listener.py (network-wide), so the two can't drift."""
from __future__ import annotations

import re

_TIER_RE = re.compile(r"\[(Low|High|Hazardous)\]", re.IGNORECASE)


def res_tier_from_signal_name(signal_name: str) -> str:
    """'Resource Extraction Site [Hazardous]' -> 'Hazardous'.
    A plain 'Resource Extraction Site' (no bracket) -> 'Nominal'."""
    if not isinstance(signal_name, str):
        return "Nominal"
    m = _TIER_RE.search(signal_name)
    return m.group(1).title() if m else "Nominal"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_res_signals.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add edc/core/res_signals.py tests/test_res_signals.py
git commit -m "feat: add shared RES-tier parsing helper"
```

---

### Task 2: Schema — two new tables

**Files:**
- Modify: `persistence/database.py` (`run_migrations()`'s `migrations` list, currently ending at line 250 with the `codex_entries.is_phenomena` ALTER)
- Test: `tests/test_bgs_status_schema.py`

**Interfaces:**
- Produces: tables `system_bgs_status` and `system_res_sites`, both with
  `system_address INTEGER PRIMARY KEY`. Consumed by Task 3's repository
  methods.

- [ ] **Step 1: Write the failing test**

```python
"""Confirms the two new BGS/RES-status tables exist after migration --
same fixture shape as test_faction_snapshot_freshness.py."""
import pytest

from persistence.database import Database
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.executescript(SCHEMA_SQL)
    database.run_migrations()
    return database


def _table_columns(db, table_name):
    rows = db.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r["name"] for r in rows}


def test_system_bgs_status_table_exists(db):
    cols = _table_columns(db, "system_bgs_status")
    assert cols == {
        "system_address", "system_name", "conflicts", "faction_states",
        "data_timestamp", "source",
    }


def test_system_res_sites_table_exists(db):
    cols = _table_columns(db, "system_res_sites")
    assert cols == {
        "system_address", "system_name", "tiers", "data_timestamp", "source",
    }


def test_system_bgs_status_upsert_keyed_on_system_address(db):
    db.execute(
        "INSERT INTO system_bgs_status (system_address, system_name, data_timestamp) VALUES (?, ?, ?)",
        (1, "Sol", "2026-08-23T00:00:00Z"),
    )
    with pytest.raises(Exception):
        db.execute(
            "INSERT INTO system_bgs_status (system_address, system_name, data_timestamp) VALUES (?, ?, ?)",
            (1, "Sol", "2026-08-23T01:00:00Z"),
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bgs_status_schema.py -v`
Expected: FAIL — `system_bgs_status`/`system_res_sites` don't exist (`sqlite3.OperationalError: no such table`)

- [ ] **Step 3: Add the two tables to the migrations list**

In `persistence/database.py`, inside `run_migrations()`'s `migrations = [...]` list, append two entries right after the existing `"ALTER TABLE codex_entries ADD COLUMN is_phenomena INTEGER DEFAULT 0",` line (the list's current last entry):

```python
            # War/CivilWar conflicts + multi-state factions -- "latest known
            # per system" (not daily history like faction_snapshots), only
            # ever written when there's something combat/BGS-relevant to
            # show. Fed live going forward only (own journal + EDDN), never
            # backfilled from old journal files -- a war recorded weeks ago
            # is very likely already resolved, so backfilling it would be
            # actively misleading rather than merely stale.
            """CREATE TABLE IF NOT EXISTS system_bgs_status (
                system_address INTEGER PRIMARY KEY,
                system_name    TEXT,
                conflicts      TEXT,
                faction_states TEXT,
                data_timestamp TEXT,
                source         TEXT
            )""",
            # RES/Low RES/High RES/Hazardous RES presence, system-level only
            # (FSSSignalDiscovered carries no ring/body granularity). Same
            # "latest known, forward-only" reasoning as system_bgs_status.
            """CREATE TABLE IF NOT EXISTS system_res_sites (
                system_address INTEGER PRIMARY KEY,
                system_name    TEXT,
                tiers          TEXT,
                data_timestamp TEXT,
                source         TEXT
            )""",
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bgs_status_schema.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add persistence/database.py tests/test_bgs_status_schema.py
git commit -m "feat: add system_bgs_status and system_res_sites tables"
```

---

### Task 3: Repository methods — save + radius search

**Files:**
- Modify: `persistence/repository.py` (add methods near `save_faction_snapshot`/`search_market_prices`)
- Test: `tests/test_bgs_status_repository.py`

**Interfaces:**
- Consumes: `Repository.db` (existing), `_normalize_data_timestamp` (existing, `repository.py:28`), `_MARKET_DATA_MAX_AGE_DAYS` (existing, `repository.py:14`).
- Produces:
  - `save_system_bgs_status(system_address: int, system_name: str, conflicts: list, factions: list, data_timestamp: str, source: str) -> None`
  - `save_system_res_tiers(system_address: int, system_name: str, tiers: list, data_timestamp: str, source: str) -> None`
  - `search_bgs_status_near(x: float, y: float, z: float, radius_ly: float) -> list[dict]` — each dict: `{system_address, system_name, distance_ly, conflicts: list[dict], faction_states: list[dict], data_timestamp}`
  - `search_res_sites_near(x: float, y: float, z: float, radius_ly: float) -> list[dict]` — each dict: `{system_address, system_name, distance_ly, tiers: list[str], data_timestamp}`

  Consumed by Task 5 (own-journal saves), Task 7 (EDDN flush saves), Task 9 (panel search).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for system_bgs_status/system_res_sites save + radius search --
real SQLite (temp file), same fixture shape as
test_faction_snapshot_freshness.py."""
import json
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


def _seed_coords(repo, system_name, x, y, z):
    repo.db.execute(
        "INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)",
        (system_name, x, y, z),
    )


# --- save_system_bgs_status ---

def test_save_skips_when_nothing_relevant(repo):
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=[{"Name": "A", "ActiveStates": []}],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is None


def test_save_stores_war_conflict_and_ignores_non_war_conflicts(repo):
    conflicts = [
        {"WarType": "election", "Status": "", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}},
        {"WarType": "war", "Status": "active", "Faction1": {"Name": "C", "WonDays": 2}, "Faction2": {"Name": "D", "WonDays": 1}},
    ]
    repo.save_system_bgs_status(1, "Sol", conflicts=conflicts, factions=[],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is not None
    stored = json.loads(row["conflicts"])
    assert len(stored) == 1
    assert stored[0] == {"faction1": "C", "faction2": "D", "war_type": "war", "status": "active", "won_days1": 2, "won_days2": 1}


def test_save_stores_multistate_factions_only(repo):
    factions = [
        {"Name": "A", "ActiveStates": [], "PendingStates": [], "RecoveringStates": []},
        {"Name": "B", "FactionState": "War", "ActiveStates": [{"State": "War"}], "PendingStates": [], "RecoveringStates": [{"State": "Outbreak"}]},
    ]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1
    assert stored[0]["name"] == "B"


def test_save_older_data_does_not_overwrite_newer(repo):
    repo.save_system_bgs_status(1, "Sol", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp="2026-08-23T10:00:00Z", source="eddn")
    repo.save_system_bgs_status(1, "Sol", conflicts=[{"WarType": "civilwar", "Faction1": {"Name": "X"}, "Faction2": {"Name": "Y"}}],
                                 factions=[], data_timestamp="2026-08-22T10:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["conflicts"])
    assert stored[0]["faction1"] == "A"  # the newer (eddn) write, not overwritten by the older journal write


# --- save_system_res_tiers ---

def test_save_res_tiers_skips_when_empty(repo):
    repo.save_system_res_tiers(1, "Sol", tiers=[], data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_res_sites WHERE system_address = 1").fetchone()
    assert row is None


def test_save_res_tiers_dedupes_and_sorts(repo):
    repo.save_system_res_tiers(1, "Sol", tiers=["High", "Low", "High", "Nominal"],
                                data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_res_sites WHERE system_address = 1").fetchone()
    assert json.loads(row["tiers"]) == ["High", "Low", "Nominal"]


# --- search_bgs_status_near / search_res_sites_near ---

def test_search_bgs_status_near_filters_by_radius(repo):
    _seed_coords(repo, "Near", 0.0, 0.0, 0.0)
    _seed_coords(repo, "Far", 500.0, 0.0, 0.0)
    repo.save_system_bgs_status(1, "Near", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp="2026-08-23T00:00:00Z", source="journal")
    repo.save_system_bgs_status(2, "Far", conflicts=[{"WarType": "war", "Faction1": {"Name": "C"}, "Faction2": {"Name": "D"}}],
                                 factions=[], data_timestamp="2026-08-23T00:00:00Z", source="journal")
    results = repo.search_bgs_status_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert [r["system_name"] for r in results] == ["Near"]


def test_search_res_sites_near_returns_tiers(repo):
    _seed_coords(repo, "Near", 0.0, 0.0, 0.0)
    repo.save_system_res_tiers(1, "Near", tiers=["Hazardous"], data_timestamp="2026-08-23T00:00:00Z", source="journal")
    results = repo.search_res_sites_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert results[0]["tiers"] == ["Hazardous"]
    assert results[0]["distance_ly"] == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bgs_status_repository.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'save_system_bgs_status'`

- [ ] **Step 3: Write the implementation**

Add to `persistence/repository.py`, near `save_faction_snapshot` (after its rolling-retention `DELETE` block, before `get_player_faction_overview`):

```python
    def save_system_bgs_status(
        self, system_address: int, system_name: str, conflicts: list, factions: list,
        data_timestamp: str, source: str,
    ) -> None:
        """
        Upserts current War/CivilWar conflicts and multi-state factions for
        a system -- skipped entirely if there's nothing combat/BGS-relevant
        to show. Freshness-guarded like save_faction_snapshot: whichever
        pipeline (own journal vs EDDN) has the more recent underlying data
        wins regardless of write order.
        """
        war_conflicts = []
        for c in (conflicts or []):
            if not isinstance(c, dict):
                continue
            war_type = str(c.get("WarType", "")).lower()
            if war_type not in ("war", "civilwar"):
                continue
            f1 = c.get("Faction1") or {}
            f2 = c.get("Faction2") or {}
            war_conflicts.append({
                "faction1": f1.get("Name"), "faction2": f2.get("Name"),
                "war_type": war_type, "status": c.get("Status"),
                "won_days1": f1.get("WonDays"), "won_days2": f2.get("WonDays"),
            })

        multistate_factions = []
        for f in (factions or []):
            if not isinstance(f, dict):
                continue
            if f.get("ActiveStates") or f.get("PendingStates") or f.get("RecoveringStates"):
                multistate_factions.append({
                    "name": f.get("Name"), "faction_state": f.get("FactionState"),
                    "active_states": f.get("ActiveStates"), "pending_states": f.get("PendingStates"),
                    "recovering_states": f.get("RecoveringStates"),
                })

        if not war_conflicts and not multistate_factions:
            return

        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO system_bgs_status (
                system_address, system_name, conflicts, faction_states, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO UPDATE SET
                system_name    = excluded.system_name,
                conflicts      = excluded.conflicts,
                faction_states = excluded.faction_states,
                data_timestamp = excluded.data_timestamp,
                source         = excluded.source
            WHERE system_bgs_status.data_timestamp IS NULL
               OR excluded.data_timestamp >= system_bgs_status.data_timestamp
            """,
            (
                system_address, system_name,
                json.dumps(war_conflicts), json.dumps(multistate_factions),
                normalized_timestamp, source,
            ),
        )

    def save_system_res_tiers(
        self, system_address: int, system_name: str, tiers: list, data_timestamp: str, source: str,
    ) -> None:
        """Upserts the RES tiers currently known present in a system --
        same freshness-guarded upsert as save_system_bgs_status. Skipped if
        tiers is empty (nothing to show)."""
        clean_tiers = sorted({t for t in (tiers or []) if isinstance(t, str) and t})
        if not clean_tiers:
            return

        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO system_res_sites (
                system_address, system_name, tiers, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO UPDATE SET
                system_name    = excluded.system_name,
                tiers          = excluded.tiers,
                data_timestamp = excluded.data_timestamp,
                source         = excluded.source
            WHERE system_res_sites.data_timestamp IS NULL
               OR excluded.data_timestamp >= system_res_sites.data_timestamp
            """,
            (system_address, system_name, json.dumps(clean_tiers), normalized_timestamp, source),
        )

    def search_bgs_status_near(self, x: float, y: float, z: float, radius_ly: float) -> list[dict]:
        """War/CivilWar + multi-state faction status for every tracked
        system within radius_ly, closest-first. Same bounding-box-then-
        Euclidean-filter pattern as search_market_prices (system_coords is
        galaxy-wide and unbounded, fed continuously by the EDDN listener).
        Rows older than _MARKET_DATA_MAX_AGE_DAYS are excluded -- a two-
        week-old "War" entry is more likely wrong than right."""
        cutoff = _market_data_cutoff()
        rows = self.db.conn.execute(
            """
            SELECT b.system_address, b.system_name, b.conflicts, b.faction_states,
                   b.data_timestamp, sc.x, sc.y, sc.z
            FROM system_bgs_status b
            INNER JOIN system_coords sc ON sc.system_name = b.system_name
            WHERE b.data_timestamp >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (cutoff, x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
        ).fetchall()

        results = []
        for r in rows:
            dist = ((r["x"] - x) ** 2 + (r["y"] - y) ** 2 + (r["z"] - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            results.append({
                "system_address": r["system_address"],
                "system_name": r["system_name"],
                "distance_ly": dist,
                "conflicts": json.loads(r["conflicts"]) if r["conflicts"] else [],
                "faction_states": json.loads(r["faction_states"]) if r["faction_states"] else [],
                "data_timestamp": r["data_timestamp"],
            })
        results.sort(key=lambda r: r["distance_ly"])
        return results

    def search_res_sites_near(self, x: float, y: float, z: float, radius_ly: float) -> list[dict]:
        """RES tier presence for every tracked system within radius_ly,
        closest-first. Same pattern/cutoff as search_bgs_status_near."""
        cutoff = _market_data_cutoff()
        rows = self.db.conn.execute(
            """
            SELECT r.system_address, r.system_name, r.tiers, r.data_timestamp, sc.x, sc.y, sc.z
            FROM system_res_sites r
            INNER JOIN system_coords sc ON sc.system_name = r.system_name
            WHERE r.data_timestamp >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (cutoff, x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
        ).fetchall()

        results = []
        for r in rows:
            dist = ((r["x"] - x) ** 2 + (r["y"] - y) ** 2 + (r["z"] - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            results.append({
                "system_address": r["system_address"],
                "system_name": r["system_name"],
                "distance_ly": dist,
                "tiers": json.loads(r["tiers"]) if r["tiers"] else [],
                "data_timestamp": r["data_timestamp"],
            })
        results.sort(key=lambda r: r["distance_ly"])
        return results
```

Note: `_market_data_cutoff()` is the existing module-level helper at
`repository.py:17-18` (`(datetime.now(timezone.utc) -
timedelta(days=_MARKET_DATA_MAX_AGE_DAYS)).strftime(...)`) — reused
as-is, not reimplemented.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bgs_status_repository.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add persistence/repository.py tests/test_bgs_status_repository.py
git commit -m "feat: add system_bgs_status/system_res_sites repository methods"
```

---

### Task 4: RES classification in the event engine (own journal)

**Files:**
- Modify: `edc/core/event_engine.py` (`_classify_system_signal` at line 217; the `FSSSignalDiscovered` handler's `entry` dict at lines 1415-1425)
- Test: `tests/test_res_signal_classification.py`

**Interfaces:**
- Consumes: `res_tier_from_signal_name` from Task 1.
- Produces: `_classify_system_signal(...)` returning `"RES"` for
  `SignalType == "ResourceExtraction"`; each `state.system_signals` entry
  for a RES signal now carries a `"Tier"` key. Consumed by Task 5 (reads
  `state.system_signals` filtered to `Category == "RES"`).

- [ ] **Step 1: Write the failing test**

```python
"""Tests for RES classification in EventEngine._classify_system_signal --
pure method (never touches self), called unbound so no GameState/
settings_base construction is needed. Matches tests/test_engage_risk.py's
"pure function, no Qt needed" structure."""
from edc.core.event_engine import EventEngine


def test_resource_extraction_signal_type_classified_as_res():
    result = EventEngine._classify_system_signal(
        None, "Resource Extraction Site [Hazardous]", "", None, "ResourceExtraction",
    )
    assert result == "RES"


def test_nominal_resource_extraction_signal_type_classified_as_res():
    result = EventEngine._classify_system_signal(
        None, "Resource Extraction Site", "", None, "ResourceExtraction",
    )
    assert result == "RES"


def test_nav_beacon_still_classified_separately_from_res():
    result = EventEngine._classify_system_signal(
        None, "Nav Beacon", "", None, "NavBeacon",
    )
    assert result == "NavBeacon"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_res_signal_classification.py -v`
Expected: FAIL — `ResourceExtraction` falls through to `"Other"`, not `"RES"`

- [ ] **Step 3: Write the implementation**

In `edc/core/event_engine.py`, add the import near the top (alongside the
existing `from edc.core.bgs_conflicts import ...` line):

```python
from edc.core.res_signals import res_tier_from_signal_name
```

In `_classify_system_signal` (line 217), add one branch right after the
`touristbeacon` check and before the `is_station` check:

```python
            if st == "touristbeacon":
                return "TouristBeacon"
            if st == "resourceextraction":
                return "RES"
            if isinstance(is_station, bool) and is_station:
```

In the `FSSSignalDiscovered` handler's `entry` dict (lines 1415-1425), add
a `"Tier"` key right after `"Category"`:

```python
            entry = {
                "Key": key,
                "SignalName": sig_name,
                "SignalType": sig_type,
                "USSType": uss,
                "Category": category,
                "Tier": res_tier_from_signal_name(sig_name) if category == "RES" else None,
                "ThreatLevel": threat if isinstance(threat, int) else None,
                "IsStation": bool(is_station) if isinstance(is_station, bool) else None,
                "TimeRemaining": time_rem if isinstance(time_rem, (int, float)) else None,
                "LastSeen": ts if isinstance(ts, str) else "",
            }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_res_signal_classification.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add edc/core/event_engine.py tests/test_res_signal_classification.py
git commit -m "feat: classify ResourceExtraction FSS signals as RES with tier"
```

---

### Task 5: Own-journal save hooks in main_window.py

**Files:**
- Modify: `edc/ui/main_window.py` (new methods near `_save_faction_snapshots` at line 455; wiring into `_on_event` at lines 2239-2240)

**Interfaces:**
- Consumes: `Repository.save_system_bgs_status`/`save_system_res_tiers`
  (Task 3), `state.system_address`/`state.system`/`state.factions`/
  `state.system_conflicts`/`state.factions_timestamp`/`state.system_signals`
  (all pre-existing `GameState` fields).
- Produces: `MainWindow._save_system_bgs_status()`,
  `MainWindow._save_system_res_tiers()`.

- [ ] **Step 1: Add the two new methods**

In `edc/ui/main_window.py`, right after `_save_faction_snapshots` (which
ends at line 472, just before `_save_ring_data`):

```python
    def _save_system_bgs_status(self):
        system_address = getattr(self.state, "system_address", None)
        if not isinstance(system_address, int):
            return
        system_name = getattr(self.state, "system", None) or ""
        factions = getattr(self.state, "factions", None) or []
        conflicts = getattr(self.state, "system_conflicts", None) or []
        timestamp = getattr(self.state, "factions_timestamp", "") or ""
        try:
            self.repo.save_system_bgs_status(
                system_address, system_name, conflicts, factions, timestamp, "journal",
            )
        except Exception:
            log.exception("Failed to save system BGS status")

    def _save_system_res_tiers(self, event_timestamp: str = ""):
        system_address = getattr(self.state, "system_address", None)
        if not isinstance(system_address, int):
            return
        system_name = getattr(self.state, "system", None) or ""
        signals = getattr(self.state, "system_signals", None) or []
        tiers = [s.get("Tier") for s in signals if isinstance(s, dict) and s.get("Category") == "RES" and s.get("Tier")]
        try:
            self.repo.save_system_res_tiers(
                system_address, system_name, tiers, event_timestamp, "journal",
            )
        except Exception:
            log.exception("Failed to save system RES tiers")
```

- [ ] **Step 2: Wire both into `_on_event`**

In `_on_event` (`edc/ui/main_window.py:2193`), change the existing block
at lines 2239-2240:

```python
        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots(self.state.factions_timestamp)
```

to:

```python
        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots(self.state.factions_timestamp)
            self._save_system_bgs_status()

        if name == "FSSSignalDiscovered":
            self._save_system_res_tiers(evt.get("timestamp") or "")
```

- [ ] **Step 3: Manual verification (per project rule — UI/live-event wiring is confirmed in the running app, not a unit test)**

Run `launch.bat`. Jump into a system known to have an active
War/CivilWar (or one with a faction sitting in an unusual state), and
separately honk (discovery scan) in a system with a ring known to have a
RES site. Confirm via a DB inspection (`sqlite3` shell or a quick
`SELECT * FROM system_bgs_status` / `SELECT * FROM system_res_sites`
against `data/edhelper.db`) that a row appears for that system after the
relevant event.

- [ ] **Step 4: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: save BGS conflict/multi-state and RES-tier status from own journal"
```

---

### Task 6: EDDN listener — new signals for BGS status and RES sites

**Files:**
- Modify: `edc/core/eddn_listener.py`
- Test: `tests/test_eddn_bgs_status_parsing.py`

**Interfaces:**
- Consumes: `res_tier_from_signal_name` (Task 1).
- Produces: `EddnPowerPlayWorker.bgs_status_seen` signal
  `(id64, StarSystem: str, conflicts: list, factions: list, timestamp: str)`;
  `EddnPowerPlayWorker.res_signal_seen` signal
  `(id64, StarSystem: str, tiers: list, timestamp: str)`. Consumed by
  Task 7/8 (`EddnMarketCache` buffering, `main_window.py` wiring).

- [ ] **Step 1: Write the failing tests**

The message-shape-parsing logic is pulled into two standalone functions
(`_extract_bgs_status`, `_extract_res_tiers`) specifically so they're
testable without a live ZMQ socket — same reasoning `_maybe_emit_faction_seen`
already exists as a separate method rather than inline in `_pump()`.

```python
"""Tests for eddn_listener.py's BGS-status/RES-signal message parsing --
pure functions, no ZMQ/network needed."""
from edc.core.eddn_listener import _extract_bgs_status, _extract_res_tiers


def test_extract_bgs_status_returns_war_conflicts_and_multistate_factions():
    msg = {
        "SystemAddress": 12345,
        "StarSystem": "HIP 22052",
        "Conflicts": [
            {"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 2}, "Faction2": {"Name": "B", "WonDays": 1}},
            {"WarType": "election", "Faction1": {"Name": "X"}, "Faction2": {"Name": "Y"}},
        ],
        "Factions": [
            {"Name": "A", "ActiveStates": [{"State": "War"}]},
            {"Name": "Z", "ActiveStates": [], "PendingStates": [], "RecoveringStates": []},
        ],
    }
    conflicts, factions = _extract_bgs_status(msg)
    assert len(conflicts) == 1 and conflicts[0]["WarType"] == "war"
    assert len(factions) == 1 and factions[0]["Name"] == "A"


def test_extract_bgs_status_empty_when_nothing_relevant():
    msg = {"SystemAddress": 1, "StarSystem": "Sol", "Conflicts": [], "Factions": [{"Name": "A"}]}
    conflicts, factions = _extract_bgs_status(msg)
    assert conflicts == [] and factions == []


def test_extract_res_tiers_from_signals_array():
    msg = {
        "SystemAddress": 12345,
        "StarSystem": "HIP 22052",
        "signals": [
            {"SignalName_Localised": "Resource Extraction Site [Hazardous]", "SignalType": "ResourceExtraction"},
            {"SignalName_Localised": "Resource Extraction Site [Low]", "SignalType": "ResourceExtraction"},
            {"SignalName_Localised": "Nav Beacon", "SignalType": "NavBeacon"},
        ],
    }
    tiers = _extract_res_tiers(msg)
    assert tiers == ["Hazardous", "Low"]


def test_extract_res_tiers_empty_when_no_res_signals():
    msg = {"SystemAddress": 1, "StarSystem": "Sol", "signals": [{"SignalName": "Nav Beacon", "SignalType": "NavBeacon"}]}
    assert _extract_res_tiers(msg) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_eddn_bgs_status_parsing.py -v`
Expected: FAIL — `_extract_bgs_status`/`_extract_res_tiers` don't exist

- [ ] **Step 3: Write the implementation**

In `edc/core/eddn_listener.py`, add near the top (module-level, after the
existing constants block):

```python
_FSSSIGNALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fsssignaldiscovered/"


def _extract_bgs_status(msg: dict) -> tuple[list, list]:
    """War/CivilWar conflicts and multi-state factions from a journal
    message's Conflicts/Factions arrays -- unconditional (any system, not
    just a squadron-watched faction), unlike _maybe_emit_faction_seen."""
    conflicts = [
        c for c in (msg.get("Conflicts") or [])
        if isinstance(c, dict) and str(c.get("WarType", "")).lower() in ("war", "civilwar")
    ]
    factions = [
        f for f in (msg.get("Factions") or [])
        if isinstance(f, dict) and (f.get("ActiveStates") or f.get("PendingStates") or f.get("RecoveringStates"))
    ]
    return conflicts, factions


def _extract_res_tiers(msg: dict) -> list:
    """Sorted, deduped RES tiers from an fsssignaldiscovered message's
    signals array."""
    from edc.core.res_signals import res_tier_from_signal_name

    tiers = set()
    for sig in (msg.get("signals") or []):
        if not isinstance(sig, dict):
            continue
        if sig.get("SignalType") != "ResourceExtraction":
            continue
        name = sig.get("SignalName_Localised") or sig.get("SignalName") or ""
        tiers.add(res_tier_from_signal_name(name))
    return sorted(tiers)
```

Add the two new signals to `EddnPowerPlayWorker` (near the existing
`faction_seen` signal declaration):

```python
    # id64, StarSystem, war conflicts (list), multi-state factions (list),
    # timestamp -- unconditional (any system), unlike faction_seen which is
    # gated to watched_factions. Feeds system_bgs_status.
    bgs_status_seen = pyqtSignal(object, str, list, list, str)
    # id64, StarSystem, RES tiers present (list), timestamp. Feeds
    # system_res_sites.
    res_signal_seen = pyqtSignal(object, str, list, str)
```

In `_pump()`, add a third schema branch right after the existing
`_FCMATERIALS_SCHEMA_PREFIX` branch (before the `if not
schema.startswith(_JOURNAL_SCHEMA_PREFIX): continue` line):

```python
            if schema.startswith(_FSSSIGNALS_SCHEMA_PREFIX):
                msg = data.get("message")
                if isinstance(msg, dict):
                    self._maybe_emit_res_signal(msg)
                continue
```

Add the call to `_maybe_emit_bgs_status` alongside the existing
squadron-gated call (in `_pump()`, right after the existing
`if self._watched_factions: self._maybe_emit_faction_seen(msg, timestamp)`
block):

```python
            if self._watched_factions:
                self._maybe_emit_faction_seen(msg, timestamp)

            self._maybe_emit_bgs_status(msg, timestamp)
```

Add the two new instance methods, right after `_maybe_emit_faction_seen`:

```python
    def _maybe_emit_bgs_status(self, msg: dict, timestamp: str) -> None:
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(star_system, str) and star_system):
            return
        conflicts, factions = _extract_bgs_status(msg)
        if not conflicts and not factions:
            return
        self.bgs_status_seen.emit(system_address, star_system, conflicts, factions, timestamp)

    def _maybe_emit_res_signal(self, msg: dict) -> None:
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(star_system, str) and star_system):
            return
        tiers = _extract_res_tiers(msg)
        if not tiers:
            return
        timestamp = msg.get("timestamp") or ""
        self.res_signal_seen.emit(system_address, star_system, tiers, timestamp)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_eddn_bgs_status_parsing.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add edc/core/eddn_listener.py tests/test_eddn_bgs_status_parsing.py
git commit -m "feat: parse network-wide BGS conflicts and RES signals from EDDN"
```

---

### Task 7: EddnMarketCache buffering for the two new signal types

**Files:**
- Modify: `edc/core/eddn_market.py`

**Interfaces:**
- Consumes: `Repository.save_system_bgs_status`/`save_system_res_tiers`
  (Task 3).
- Produces: `EddnMarketCache.on_bgs_status_seen(system_address, system_name,
  conflicts, factions, timestamp)`, `EddnMarketCache.on_res_signal_seen(
  system_address, system_name, tiers, timestamp)`; `pop_buffers()`/
  `flush()`/`write_buffers()` now return/accept 9 collections instead of 7.
  Consumed by Task 8 (`main_window.py` wiring).

- [ ] **Step 1: Add the two new buffers**

In `EddnMarketCache.__init__` (`edc/core/eddn_market.py`), right after the
existing `_carrier_access_buffer` line:

```python
        # Keyed by system_address -- War/CivilWar conflicts + multi-state
        # factions from any commander's journal/1 message, deduped so
        # re-sightings between flushes cost one write, not one per sighting.
        self._bgs_status_buffer: Dict[int, Tuple[str, list, list, str]] = {}
        # Keyed by system_address -- RES tiers present, from any
        # commander's fsssignaldiscovered/1 message.
        self._res_sites_buffer: Dict[int, Tuple[str, list, str]] = {}
```

- [ ] **Step 2: Add the two new slot methods**

Right after `on_faction_seen`:

```python
    def on_bgs_status_seen(self, system_address: int, system_name: str, conflicts: list, factions: list, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._bgs_status_buffer[system_address] = (system_name, conflicts, factions, timestamp)

    def on_res_signal_seen(self, system_address: int, system_name: str, tiers: list, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._res_sites_buffer[system_address] = (system_name, tiers, timestamp)
```

- [ ] **Step 3: Extend `buffered_counts`, `pop_buffers`, `flush`, `write_buffers`**

Update `buffered_counts` to an 8-tuple:

```python
    def buffered_counts(self) -> Tuple[int, int, int, int, int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count,
        station_count, fcmaterials_count, carrier_access_count,
        bgs_status_count, res_sites_count) currently buffered -- for
        status/logging."""
        return (
            len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer),
            len(self._station_buffer), len(self._fcmaterials_buffer), len(self._carrier_access_buffer),
            len(self._bgs_status_buffer), len(self._res_sites_buffer),
        )
```

Update `pop_buffers` to return 9 collections:

```python
    def pop_buffers(self):
        """
        Snapshots and clears all nine buffers, returning their contents as
        plain lists/tuples -- for handing off to a background worker with
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
        bgs_status = list(self._bgs_status_buffer.items())
        res_sites = list(self._res_sites_buffer.items())
        self._coord_buffer.clear()
        self._market_buffer.clear()
        self._faction_buffer.clear()
        self._station_buffer.clear()
        self._codex_buffer.clear()
        self._fcmaterials_buffer.clear()
        self._carrier_access_buffer.clear()
        self._bgs_status_buffer.clear()
        self._res_sites_buffer.clear()
        return coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites

    def flush(self) -> None:
        """Synchronous flush on the caller's own thread/connection -- see
        the module docstring; only safe on the main thread, only at
        shutdown."""
        coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites = self.pop_buffers()
        write_buffers(self._repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites)
```

Update `write_buffers`'s signature and add the two new write blocks at the
end (right after the existing `carrier_access` block):

```python
def write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites) -> None:
```

```python
    if bgs_status:
        for system_address, (system_name, conflicts, factions_list, timestamp) in bgs_status:
            try:
                repo.save_system_bgs_status(system_address, system_name, conflicts, factions_list, timestamp, "eddn")
            except Exception:
                log.exception("Failed to flush BGS status for system_address=%s", system_address)

    if res_sites:
        for system_address, (system_name, tiers, timestamp) in res_sites:
            try:
                repo.save_system_res_tiers(system_address, system_name, tiers, timestamp, "eddn")
            except Exception:
                log.exception("Failed to flush RES sites for system_address=%s", system_address)
```

- [ ] **Step 4: Run the existing EDDN market test suite to confirm nothing broke**

Run: `.venv\Scripts\python.exe -m pytest tests/test_fleet_carrier_materials.py tests/test_carrier_docking_access.py -v`
Expected: PASS (these exercise `write_buffers`/`pop_buffers` indirectly — confirms the signature change didn't break existing callers within this file)

- [ ] **Step 5: Commit**

```bash
git add edc/core/eddn_market.py
git commit -m "feat: buffer and flush EDDN-sourced BGS status and RES sites"
```

---

### Task 8: Wire the two new EDDN signals into main_window.py

**Files:**
- Modify: `edc/ui/main_window.py` (`_start_eddn_listener` at line 1783; `_EddnFlushWorker` class at line 290; `_on_market_flush_tick` at line 4256)

**Interfaces:**
- Consumes: `EddnPowerPlayWorker.bgs_status_seen`/`res_signal_seen` (Task 6),
  `EddnMarketCache.on_bgs_status_seen`/`on_res_signal_seen`/`pop_buffers`
  (Task 7), `write_buffers` (Task 7, now 9-arg).

- [ ] **Step 1: Connect the two new signals in `_start_eddn_listener`**

Right after the existing `self._eddn_worker.station_seen.connect(...)`/
`codex_entry_seen.connect(...)`/`fcmaterials_seen.connect(...)` lines
(`main_window.py:1808-1810`):

```python
        self._eddn_worker.bgs_status_seen.connect(self.eddn_market_cache.on_bgs_status_seen)
        self._eddn_worker.res_signal_seen.connect(self.eddn_market_cache.on_res_signal_seen)
```

- [ ] **Step 2: Extend `_EddnFlushWorker` to carry the two new buffers through**

Replace the class body (`main_window.py:290-326`) with:

```python
class _EddnFlushWorker(QObject):
    """
    Writes a snapshot of EddnMarketCache's buffered EDDN data (popped by
    the main thread via pop_buffers(), which is cheap) plus a WAL
    checkpoint -- both used to run directly on the main thread every 45s
    via QTimer, freezing the UI for however long the batch write took.
    Confirmed live: noticeably worse right after docking at a busy
    station's market, since that's exactly when buffered commodity/
    station/faction data peaks. Opens its own connection per the
    project's cross-thread SQLite rule.
    """
    finished = pyqtSignal()

    def __init__(self, db_path, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites):
        super().__init__()
        self._db_path = db_path
        self._coords, self._market, self._factions = coords, market, factions
        self._stations, self._codex, self._fcmaterials = stations, codex, fcmaterials
        self._carrier_access = carrier_access
        self._bgs_status, self._res_sites = bgs_status, res_sites

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            write_buffers(
                repo, self._coords, self._market, self._factions, self._stations,
                self._codex, self._fcmaterials, self._carrier_access,
                self._bgs_status, self._res_sites,
            )
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            log.exception("Background EDDN flush failed")
        finally:
            db.close()
        self.finished.emit()
```

- [ ] **Step 3: Update `_on_market_flush_tick`**

Replace `main_window.py:4256-4275` with:

```python
    def _on_market_flush_tick(self) -> None:
        """
        Pops the buffered EDDN data (cheap, main-thread dict ops) and hands
        it to a background worker for the actual writes + WAL checkpoint --
        see _EddnFlushWorker for why this moved off the main thread.
        """
        if self._flush_thread and self._flush_thread.isRunning():
            return  # previous flush still running — next tick will catch up
        coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites = self.eddn_market_cache.pop_buffers()
        if not (coords or market or factions or stations or codex or fcmaterials or carrier_access or bgs_status or res_sites):
            return

        self._flush_worker = _EddnFlushWorker(
            self.repo.db.db_path, coords, market, factions, stations, codex, fcmaterials, carrier_access,
            bgs_status, res_sites,
        )
        self._flush_thread = QThread()
        self._flush_worker.moveToThread(self._flush_thread)
        self._flush_thread.started.connect(self._flush_worker.run)
        self._flush_worker.finished.connect(self._flush_thread.quit)
        self._flush_thread.start()
```

- [ ] **Step 4: Manual verification**

Run `launch.bat` with "Contribute data to EDDN" and the EDDN listener
both active (default). Wait a couple of minutes (EDDN traffic is
constant), then inspect `system_bgs_status`/`system_res_sites` for rows
with `source = 'eddn'` for systems never personally visited this session.

- [ ] **Step 5: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: wire EDDN BGS-status and RES-signal buffers into the flush cycle"
```

---

### Task 9: New panel — radius search UI

**Files:**
- Create: `edc/ui/panels/combat_bgs_status_panel.py`

**Interfaces:**
- Consumes: `Repository.search_bgs_status_near`/`search_res_sites_near`
  (Task 3), `Repository.get_player_faction_overview` (pre-existing,
  `repository.py:470`), `state.system`/`state.system_x/y/z`/`state.pp_power`
  (pre-existing `GameState` fields, same ones `market_panel.py`/
  `combat_panel.py` already read).
- Produces: `CombatBgsStatusPanel(repo, parent=None)` with
  `.refresh(state) -> None`. Consumed by Task 10 (`combat_panel.py`).

- [ ] **Step 1: Write the panel**

```python
"""Combat tab's System Status sub-panel -- radius search over
system_bgs_status/system_res_sites (War/CivilWar conflicts, multi-state
factions, RES tier presence), same self-contained radius-search shape as
market_panel.py (own repo reference, own QThread search worker with its
own DB connection per the project's cross-thread SQLite rule)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)

_LABEL_STYLE = "color:#c8c8c8; background:transparent; border:none;"
_ACCENT_BG = QColor(26, 58, 90)   # squadron-relevant row highlight
_ACCENT_FG = QColor(255, 179, 71)


class _SearchWorker(QObject):
    finished = pyqtSignal(list, list)  # (bgs_status_results, res_results)

    def __init__(self, db_path, x, y, z, radius_ly):
        super().__init__()
        self._db_path = db_path
        self._x, self._y, self._z, self._radius_ly = x, y, z, radius_ly

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        try:
            bgs_results = repo.search_bgs_status_near(self._x, self._y, self._z, float(self._radius_ly))
            res_results = repo.search_res_sites_near(self._x, self._y, self._z, float(self._radius_ly))
        except Exception:
            log.exception("BGS/RES status search failed")
            bgs_results, res_results = [], []
        finally:
            db.close()
        self.finished.emit(bgs_results, res_results)


def _merge_results(bgs_results: List[dict], res_results: List[dict]) -> List[Dict[str, Any]]:
    """One row per system_name, combining conflict/faction-state data with
    RES tier data -- most systems will only have one of the two."""
    merged: Dict[str, Dict[str, Any]] = {}
    for r in bgs_results:
        merged[r["system_name"]] = {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": r["conflicts"], "faction_states": r["faction_states"],
            "tiers": [], "data_timestamp": r["data_timestamp"],
        }
    for r in res_results:
        row = merged.setdefault(r["system_name"], {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": [], "faction_states": [], "tiers": [], "data_timestamp": r["data_timestamp"],
        })
        row["tiers"] = r["tiers"]
        if r["data_timestamp"] > row.get("data_timestamp", ""):
            row["data_timestamp"] = r["data_timestamp"]
    return sorted(merged.values(), key=lambda r: r["distance_ly"])


def _conflicts_text(conflicts: List[dict]) -> str:
    if not conflicts:
        return ""
    parts = []
    for c in conflicts:
        label = "War" if c.get("war_type") == "war" else "Civil War"
        parts.append(f"{label}: {c.get('faction1')} ({c.get('won_days1')}) vs {c.get('faction2')} ({c.get('won_days2')})")
    return " | ".join(parts)


def _faction_states_text(faction_states: List[dict]) -> str:
    if not faction_states:
        return ""
    parts = []
    for f in faction_states:
        states = [s.get("State") for s in (f.get("active_states") or []) if isinstance(s, dict) and s.get("State")]
        if states:
            parts.append(f"{f.get('name')}: {', '.join(states)}")
    return " | ".join(parts)


class CombatBgsStatusPanel(QWidget):
    """Owns all widgets and refresh logic for the Combat > System Status
    sub-tab. Receives state via refresh(state); knows nothing about
    main_window or CombatPanel."""

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._squadron_faction: Optional[str] = None
        self._pp_power: str = ""
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[_SearchWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(self._location_label)

        row = QHBoxLayout()
        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 5000)
        self._range_spin.setSingleStep(10)
        self._range_spin.setValue(100)
        self._range_spin.setSuffix(" ly")
        self._range_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

        self._search_btn = QPushButton("Search")
        self._search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._search_btn.clicked.connect(self._start_search)

        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(self._search_btn)
        row.addStretch(1)
        root.addLayout(row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["System", "Distance", "War / Civil War", "Faction States", "RES Tiers"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

    def refresh(self, state) -> None:
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._pp_power = (getattr(state, "pp_power", None) or "").strip()
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))

    def _start_search(self) -> None:
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return
        if self._search_thread and self._search_thread.isRunning():
            return

        try:
            overview = self._repo.get_player_faction_overview()
            self._squadron_faction = overview["faction_name"] if overview else None
        except Exception:
            log.exception("Failed to load squadron faction for highlight matching")
            self._squadron_faction = None

        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Searching within {self._range_spin.value()} ly of {self._system}…")
        self._table.setRowCount(0)

        self._search_worker = _SearchWorker(
            self._repo.db.db_path, self._ref_x, self._ref_y, self._ref_z, self._range_spin.value(),
        )
        self._search_thread = QThread()
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.start()

    def _on_search_finished(self, bgs_results: list, res_results: list) -> None:
        self._search_btn.setEnabled(True)
        rows = _merge_results(bgs_results, res_results)
        self._status_label.setText(
            f"Found {len(rows)} system{'s' if len(rows) != 1 else ''} with active War/CivilWar, "
            f"multi-state factions, or RES presence within {self._range_spin.value()} ly of {self._system}."
        )

        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            is_squadron_relevant = bool(
                self._squadron_faction and (
                    any(f.get("name") == self._squadron_faction for f in row["faction_states"])
                    or any(c.get("faction1") == self._squadron_faction or c.get("faction2") == self._squadron_faction for c in row["conflicts"])
                )
            )
            age_txt, _ = fmt.relative_time(row.get("data_timestamp") or "")

            items = [
                QTableWidgetItem(row["system_name"]),
                QTableWidgetItem(f"{row['distance_ly']:.1f} ly"),
                QTableWidgetItem(_conflicts_text(row["conflicts"])),
                QTableWidgetItem(_faction_states_text(row["faction_states"])),
                QTableWidgetItem(", ".join(row["tiers"])),
            ]
            for c, item in enumerate(items):
                if is_squadron_relevant:
                    item.setBackground(_ACCENT_BG)
                    item.setForeground(_ACCENT_FG)
                self._table.setItem(r, c, item)
            self._table.item(r, 0).setToolTip(f"Last confirmed {age_txt}")
```

- [ ] **Step 2: Manual verification**

Run `launch.bat`, navigate to Combat (once Task 10 wires it in), click
Search with the default 100 ly radius. Confirm the table populates with
systems from the DB rows Task 5/8 already produced, and that a row
matching the squadron's faction (set earlier this session via "Set
faction manually…" or a live sighting) renders with the accent highlight.

- [ ] **Step 3: Commit**

```bash
git add edc/ui/panels/combat_bgs_status_panel.py
git commit -m "feat: add Combat System Status radius-search panel"
```

---

### Task 10: Restructure CombatPanel into Overview + System Status tabs

**Files:**
- Modify: `edc/ui/panels/combat_panel.py`

**Interfaces:**
- Consumes: `CombatBgsStatusPanel` (Task 9).
- Produces: `CombatPanel(repo, parent=None)` (constructor now takes
  `repo`); `.refresh(state)` unchanged externally, now also forwards to
  the new sub-panel. Consumed by Task 11 (no signature-visible change
  needed there beyond passing `repo` at construction — see Step 3).

- [ ] **Step 1: Wrap the existing content in an inner `QTabWidget`**

In `edc/ui/panels/combat_panel.py`, add the import:

```python
from PyQt6.QtWidgets import QTabWidget
```

and

```python
from edc.ui.panels.combat_bgs_status_panel import CombatBgsStatusPanel
```

Change the constructor signature (line 28) from:

```python
    def __init__(self, parent=None):
```

to:

```python
    def __init__(self, repo, parent=None):
```

Immediately after `outer = QVBoxLayout(self)` / `outer.setContentsMargins(0, 0, 0, 0)` /
`outer.setSpacing(0)` (lines 31-33), insert the inner tab widget and
retarget the existing header/scroll-area construction to add to an
"Overview" page instead of directly to `outer`:

```python
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        inner_tabs = QTabWidget()
        outer.addWidget(inner_tabs, 1)

        overview_page = QWidget()
        page_l = QVBoxLayout(overview_page)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.setSpacing(0)
        inner_tabs.addTab(overview_page, "Overview")
```

Then change every subsequent `outer.addWidget(...)` call in `__init__`
(there are two: the header strip's `outer.addWidget(hdr, 0)` and the
scroll area's `outer.addWidget(scroll, 1)`) to target `page_l` instead of
`outer`:

```python
        page_l.addWidget(hdr, 0)
```

```python
        page_l.addWidget(scroll, 1)
```

Finally, add the new sub-panel as a second tab, right after the combat
contacts card's `content_l.addWidget(card)` (the last line of `__init__`,
line 333):

```python
        content_l.addWidget(card)

        self.bgs_status_panel = CombatBgsStatusPanel(repo)
        inner_tabs.addTab(self.bgs_status_panel, "System Status")
```

- [ ] **Step 2: Forward `refresh(state)` to the new sub-panel**

At the top of `refresh(self, state)` (line 335), add:

```python
    def refresh(self, state):
        try:
            self.bgs_status_panel.refresh(state)
        except Exception:
            log.exception("CombatPanel.bgs_status_panel.refresh failed")

        try:
            self._refresh_notoriety_card(state)
```

(the existing `try: self._refresh_notoriety_card(state) ...` block stays
exactly as-is, just gains this one new block ahead of it).

- [ ] **Step 3: Update the construction call site in main_window.py**

In `edc/ui/main_window.py:1445`, change:

```python
        self.combat_panel = CombatPanel()
```

to:

```python
        self.combat_panel = CombatPanel(self.repo)
```

- [ ] **Step 4: Manual verification**

Run `launch.bat`. Open the Combat tab — confirm "Overview" (existing
notoriety/bounty/fine/massacre/CZ/contacts cards, unchanged) and "System
Status" (Task 9's new panel) both render as sub-tabs, and that switching
between them and back doesn't lose any existing Combat functionality
(bounty/fine cards still populate, combat contacts table still updates
live).

- [ ] **Step 5: Commit**

```bash
git add edc/ui/panels/combat_panel.py edc/ui/main_window.py
git commit -m "feat: split Combat tab into Overview and System Status sub-tabs"
```

---

### Task 11: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the new tab to the feature list and data-source table**

Near the existing EDDN-sourced feature bullets (around line 52, the
squadron-faction network-wide tracking bullet), add:

```markdown
- Combat > System Status: War/CivilWar conflicts, multi-state factions (e.g. War+Outbreak), and RES/Low RES/High RES/Hazardous RES presence for every tracked system within a configurable radius — sourced from both the player's own journal and a live EDDN subscription, same radius-search shape as the Market tab. RES signal detection is system-level only (no ring/body granularity); status reflects the most recently confirmed sighting, not full history, and results older than 14 days are excluded from search rather than shown as possibly-stale current state.
```

Near the `market_prices`/`station_info` rows of the DB-table documentation
(around line 353-354), add two rows:

```markdown
| `system_bgs_status` | Latest known War/CivilWar conflicts and multi-state factions per system, from journal visits and EDDN — one row per system, not daily history |
| `system_res_sites` | Latest known RES/Low RES/High RES/Hazardous RES tier presence per system, from journal visits and EDDN |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the Combat System Status tab and its data sources"
```

---

## Self-Review Notes

- **Spec coverage:** War/CivilWar (Tasks 2-8), multi-state factions
  (Tasks 2-8, same tables/pipeline as conflicts), RES tiers (Tasks 1-8),
  radius selector matching Market/Mining/Trade-Route-Loop-Planner (Task 9),
  squadron/PP-faction highlighting (Task 9's `is_squadron_relevant`),
  "under Combat as a new tab" (Task 10), storage/schema (Task 2), and the
  30-days-vs-1-week retention question (spec's Design section: freshness
  badge + 14-day search cutoff reusing `_MARKET_DATA_MAX_AGE_DAYS`, no row
  deletion) are all covered. Restore/mining/massacre missions are
  explicitly out of scope per the spec's Non-Goals (no EDDN schema exists
  for them).
- **Placeholder scan:** no task contains "TBD"/"similar to Task N"/
  unexplained "add error handling" — every step has literal, complete code.
- **Type/name consistency check:** `res_tier_from_signal_name` (Task 1) is
  imported identically in Task 4 (`event_engine.py`) and Task 6
  (`eddn_listener.py`, via `_extract_res_tiers`). `save_system_bgs_status`/
  `save_system_res_tiers` (Task 3) signatures match their call sites in
  Task 5 (own journal) and Task 7's `write_buffers` (EDDN). The
  `pop_buffers()`/`write_buffers()`/`_EddnFlushWorker` 9-tuple shape is
  identical across Task 7 (definition) and Task 8 (call sites) — verified
  argument order matches everywhere (`coords, market, factions, stations,
  codex, fcmaterials, carrier_access, bgs_status, res_sites`).
  `CombatBgsStatusPanel(repo)` (Task 9) matches its construction in Task 10
  (`CombatBgsStatusPanel(repo)`) and `CombatPanel(repo)` matches Task 10's
  updated `main_window.py` call site.
