# Session BGS Activity Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new, separate panel showing every faction's mission/combat/CZ/trade activity, grouped by system, since the last detected BGS tick — across every system visited this session, not scoped to one target faction.

**Architecture:** Three new SQLite tables (`faction_combat_bonds`, `faction_cz_kills`, `faction_trade_sold`) alongside the existing `faction_mission_completions`, each fed by a new `main_window.py` event hook mirroring `_record_faction_mission_completion`'s existing pattern. One new `Repository.get_session_activity_report(since)` aggregates all four tables, grouped `{system_name: {faction_name: {...}}}`. A new read-only `SessionActivityDialog` (mirrors `FactionExpansionDialog`'s shape) renders it, launched from a new button on `PlayerFactionPanel` next to the existing "Faction Expansion Tracker…" button. The session boundary reuses the already-live `PlayerFactionPanel._latest_known_tick` (kept fresh by the existing `_BgsTickCheckWorker` timer) — no new tick-fetching code needed.

**Tech Stack:** Python, PyQt6, SQLite (via `persistence/database.py`'s `Database`/`Repository`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-session-bgs-activity-report-design.md`

## Global Constraints

- Every new table follows `faction_mission_completions`'s exact shape: one row per event, `system_address`/`faction_name`/timestamp, no session-reset logic — "session" is a query-time `>=` filter against real timestamped rows, applied by the report query only.
- Every new `main_window.py` hook wraps its `repo.save_*`/`repo.record_*` call in `try/except Exception: log.exception(...)`, matching every existing hook of this shape (`_record_faction_mission_completion`, `_save_faction_snapshots`).
- `Bounty` vouchers are excluded from `faction_combat_bonds` — the journal's `Bounty` event carries `VictimFaction` (who was killed), not which faction credits the voucher (that's determined later, at redemption, not at kill time). Only `FactionKillBond` (which carries `AwardingFaction` directly) is tracked.
- All new SQL migrations go in `persistence/database.py`'s `run_migrations()` `personal_migrations` list as `CREATE TABLE IF NOT EXISTS`, matching every other new table added this way (idempotent, safe to run on every startup).
- TDD throughout: write the failing test, run it, confirm it fails for the right reason, implement, run again, confirm green, commit.

---

### Task 1: `faction_combat_bonds` table + repository methods

**Files:**
- Modify: `persistence/database.py` (add table to `run_migrations()`'s `personal_migrations` list, near the other `faction_*` tables)
- Modify: `persistence/repository.py` (add `record_faction_combat_bond`/`get_faction_combat_bonds_since` methods, near `record_faction_mission_completion`)
- Test: `tests/test_faction_combat_bonds.py` (new file)

**Interfaces:**
- Produces: `Repository.record_faction_combat_bond(system_address: int, faction_name: str, reward: int, earned_at: str) -> None`
- Produces: `Repository.get_faction_combat_bonds_since(since: str) -> list[dict]` — each dict `{"system_address", "faction_name", "reward", "earned_at"}`, used by Task 6's aggregate query.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_combat_bonds.py`:

```python
"""Repository.record_faction_combat_bond / get_faction_combat_bonds_since
-- persists FactionKillBond rewards per system+faction for the new
session BGS activity report. Bounty vouchers are deliberately excluded
(the journal's Bounty event carries VictimFaction, not which faction
actually credits the voucher -- that's determined later, at redemption).
Real SQLite (temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_bond(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "reward": 15000, "earned_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_bonds_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-24T10:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_multiple_bonds_accumulate(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 5000, "2026-09-25T11:00:00Z")
    repo.record_faction_combat_bond(999, "Hungarian Wolves", 8000, "2026-09-25T12:00:00Z")
    rows = repo.get_faction_combat_bonds_since("2026-09-25T00:00:00Z")
    assert len(rows) == 3
    assert sum(r["reward"] for r in rows) == 28000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_combat_bonds.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'record_faction_combat_bond'`

- [ ] **Step 3: Add the table migration**

In `persistence/database.py`, inside `run_migrations()`'s `personal_migrations` list, add (place it after the `systems` PowerPlay-column migrations added earlier this session):

```python
            # Session BGS activity report -- FactionKillBond rewards only
            # (Bounty vouchers excluded: the journal's Bounty event carries
            # VictimFaction, not which faction actually credits the
            # voucher -- that's determined later, at redemption, not at
            # kill time). One row per bond, queried with a >= timestamp
            # filter at report time -- no session-reset logic needed here.
            """CREATE TABLE IF NOT EXISTS faction_combat_bonds (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                system_address INTEGER NOT NULL,
                faction_name   TEXT    NOT NULL,
                reward         INTEGER NOT NULL,
                earned_at      TEXT    NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_faction_combat_bonds_lookup
               ON faction_combat_bonds (earned_at)""",
```

- [ ] **Step 4: Implement the repository methods**

In `persistence/repository.py`, add near `record_faction_mission_completion`:

```python
    def record_faction_combat_bond(
        self, system_address: int, faction_name: str, reward: int, earned_at: str,
    ) -> None:
        """One row per FactionKillBond, for the session BGS activity
        report -- see main_window.py's _record_faction_combat_bond."""
        self.db.execute(
            "INSERT INTO faction_combat_bonds (system_address, faction_name, reward, earned_at) "
            "VALUES (?, ?, ?, ?)",
            (system_address, faction_name, reward, earned_at),
        )

    def get_faction_combat_bonds_since(self, since: str) -> list[dict]:
        """Every combat bond earned_at >= since (an ISO UTC timestamp --
        lexicographic comparison works directly). Feeds
        get_session_activity_report()."""
        rows = self.db.execute(
            "SELECT system_address, faction_name, reward, earned_at "
            "FROM faction_combat_bonds WHERE earned_at >= ?",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_combat_bonds.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_faction_combat_bonds.py
git commit -m "feat: persist FactionKillBond rewards per system+faction for the session activity report"
```

---

### Task 2: `faction_cz_kills` table + repository methods

**Files:**
- Modify: `persistence/database.py`
- Modify: `persistence/repository.py`
- Test: `tests/test_faction_cz_kills.py` (new file)

**Interfaces:**
- Produces: `Repository.record_faction_cz_kill(system_address: int, faction_name: str, zone_type: str, size: str, earned_at: str) -> None` (`zone_type` is `"ground"` or `"space"`, `size` is `"l"`/`"m"`/`"h"`)
- Produces: `Repository.get_faction_cz_kills_since(since: str) -> list[dict]` — each dict `{"system_address", "faction_name", "zone_type", "size", "earned_at"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_cz_kills.py`:

```python
"""Repository.record_faction_cz_kill / get_faction_cz_kills_since --
persists conflict-zone kill credits (ground/space, small/medium/high)
per system+faction for the session BGS activity report. Real SQLite
(temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_kill(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T10:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "zone_type": "space", "size": "h", "earned_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_kills_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "m", "2026-09-24T10:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_ground_and_space_kills_both_tracked(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "l", "2026-09-25T10:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T11:00:00Z")
    rows = repo.get_faction_cz_kills_since("2026-09-25T00:00:00Z")
    assert {(r["zone_type"], r["size"]) for r in rows} == {("ground", "l"), ("space", "h")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_cz_kills.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'record_faction_cz_kill'`

- [ ] **Step 3: Add the table migration**

In `persistence/database.py`'s `personal_migrations` list, add after Task 1's table:

```python
            """CREATE TABLE IF NOT EXISTS faction_cz_kills (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                system_address INTEGER NOT NULL,
                faction_name   TEXT    NOT NULL,
                zone_type      TEXT    NOT NULL,
                size           TEXT    NOT NULL,
                earned_at      TEXT    NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_faction_cz_kills_lookup
               ON faction_cz_kills (earned_at)""",
```

- [ ] **Step 4: Implement the repository methods**

In `persistence/repository.py`, add near `record_faction_combat_bond`:

```python
    def record_faction_cz_kill(
        self, system_address: int, faction_name: str, zone_type: str, size: str, earned_at: str,
    ) -> None:
        """One row per confirmed CZ kill credit -- see event_engine.py's
        _credit_cz_kill for how ground/space and size are inferred, and
        main_window.py's _record_faction_cz_kill for how it gets here."""
        self.db.execute(
            "INSERT INTO faction_cz_kills (system_address, faction_name, zone_type, size, earned_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (system_address, faction_name, zone_type, size, earned_at),
        )

    def get_faction_cz_kills_since(self, since: str) -> list[dict]:
        """Every CZ kill earned_at >= since. Feeds get_session_activity_report()."""
        rows = self.db.execute(
            "SELECT system_address, faction_name, zone_type, size, earned_at "
            "FROM faction_cz_kills WHERE earned_at >= ?",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_cz_kills.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_faction_cz_kills.py
git commit -m "feat: persist CZ kill credits per system+faction for the session activity report"
```

---

### Task 3: `faction_trade_sold` table + repository methods

**Files:**
- Modify: `persistence/database.py`
- Modify: `persistence/repository.py`
- Test: `tests/test_faction_trade_sold.py` (new file)

**Interfaces:**
- Produces: `Repository.record_faction_trade_sold(system_address: int, faction_name: str, kind: str, value: int, sold_at: str) -> None` (`kind` is `"commodity"`, `"exploration"`, or `"exobiology"`)
- Produces: `Repository.get_faction_trade_sold_since(since: str) -> list[dict]` — each dict `{"system_address", "faction_name", "kind", "value", "sold_at"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_trade_sold.py`:

```python
"""Repository.record_faction_trade_sold / get_faction_trade_sold_since --
persists commodity/exploration/exobiology sale value credited to the
selling station's controlling faction, per system, for the session BGS
activity report. Real SQLite (temp file), matching this repo's
convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_records_and_reads_back_a_sale(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert rows == [{
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "commodity", "value": 63085, "sold_at": "2026-09-25T10:00:00Z",
    }]


def test_excludes_sales_before_the_since_timestamp(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-24T10:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert rows == []


def test_all_three_kinds_tracked(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-25T11:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exobiology", 1804100, "2026-09-25T12:00:00Z")
    rows = repo.get_faction_trade_sold_since("2026-09-25T00:00:00Z")
    assert {r["kind"] for r in rows} == {"commodity", "exploration", "exobiology"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_trade_sold.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'record_faction_trade_sold'`

- [ ] **Step 3: Add the table migration**

In `persistence/database.py`'s `personal_migrations` list, add after Task 2's table:

```python
            """CREATE TABLE IF NOT EXISTS faction_trade_sold (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                system_address INTEGER NOT NULL,
                faction_name   TEXT    NOT NULL,
                kind           TEXT    NOT NULL,
                value          INTEGER NOT NULL,
                sold_at        TEXT    NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_faction_trade_sold_lookup
               ON faction_trade_sold (sold_at)""",
```

- [ ] **Step 4: Implement the repository methods**

In `persistence/repository.py`, add near `record_faction_cz_kill`:

```python
    def record_faction_trade_sold(
        self, system_address: int, faction_name: str, kind: str, value: int, sold_at: str,
    ) -> None:
        """One row per commodity/exploration/exobiology sale, credited to
        the selling station's controlling faction (selling only happens
        while docked, so the current system's controlling faction at sale
        time is correct) -- see main_window.py's
        _record_faction_trade_sold."""
        self.db.execute(
            "INSERT INTO faction_trade_sold (system_address, faction_name, kind, value, sold_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (system_address, faction_name, kind, value, sold_at),
        )

    def get_faction_trade_sold_since(self, since: str) -> list[dict]:
        """Every sale sold_at >= since. Feeds get_session_activity_report()."""
        rows = self.db.execute(
            "SELECT system_address, faction_name, kind, value, sold_at "
            "FROM faction_trade_sold WHERE sold_at >= ?",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_faction_trade_sold.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_faction_trade_sold.py
git commit -m "feat: persist trade/exploration/exobiology sale value per system+faction for the session activity report"
```

---

### Task 4: `get_session_activity_report` aggregate query

**Files:**
- Modify: `persistence/repository.py` (add near `get_faction_mission_completion_counts`)
- Test: `tests/test_session_activity_report.py` (new file)

**Interfaces:**
- Consumes: `get_faction_combat_bonds_since`, `get_faction_cz_kills_since`, `get_faction_trade_sold_since` (Tasks 1-3), and the existing `faction_mission_completions` table (queried directly by a new method, mirroring `get_faction_mission_completion_counts`'s own query shape).
- Produces: `Repository.get_session_activity_report(since: str) -> dict` — shape:
  ```python
  {
      "<system_name>": {
          "<faction_name>": {
              "missions": {"count": int, "weighted": int, "primary_count": int, "secondary_count": int},
              "combat_bonds_total": int,
              "cz_kills": {"ground_l": int, "ground_m": int, "ground_h": int, "space_l": int, "space_m": int, "space_h": int},
              "trade_sold": {"commodity": int, "exploration": int, "exobiology": int},
          },
          ...
      },
      ...
  }
  ```
  `system_name` is resolved via a join against the `systems` table (`system_address -> system_name`); a `system_address` with no matching `systems` row is skipped (can't label it, and every row-producing event already goes through code paths that create a `systems` row first, e.g. `save_system_name_if_missing`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_activity_report.py`:

```python
"""Repository.get_session_activity_report(since) -- aggregates missions,
combat bonds, CZ kills, and trade/exploration/exobiology sales into
{system_name: {faction_name: {...}}}, for the session BGS activity
report (a whole-session, all-faction view -- distinct from the Faction
Expansion tracker, which is scoped to one target faction/system). Real
SQLite (temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_system(repo, system_address, system_name):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )


def test_empty_report_with_no_activity(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_session_activity_report("2026-09-25T00:00:00Z") == {}


def test_missions_are_grouped_by_system_and_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(12345, "Elite United Worlds", "2026-09-25T10:00:00Z", influence_tier="++", is_primary=True)
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["Ekono"]["Elite United Worlds"]["missions"] == {
        "count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
    }


def test_combat_bonds_are_summed_per_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 5000, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 20000


def test_cz_kills_are_bucketed_by_zone_and_size(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T10:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T11:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "l", "2026-09-25T12:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    cz = report["Ekono"]["Elite United Worlds"]["cz_kills"]
    assert cz == {"ground_l": 1, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2}


def test_trade_sold_is_bucketed_by_kind(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    trade = report["Ekono"]["Elite United Worlds"]["trade_sold"]
    assert trade == {"commodity": 63085, "exploration": 1305717, "exobiology": 0}


def test_multiple_systems_and_factions_stay_separate(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    _seed_system(repo, 999, "Aiga")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(999, "Hungarian Wolves", 2000, "2026-09-25T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert set(report.keys()) == {"Ekono", "Aiga"}
    assert report["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 1000
    assert report["Aiga"]["Hungarian Wolves"]["combat_bonds_total"] == 2000


def test_activity_before_since_is_excluded(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-24T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report == {}


def test_system_with_no_systems_row_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    # No _seed_system call -- system_address 12345 has no systems row.
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_report.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'get_session_activity_report'`

- [ ] **Step 3: Implement the aggregate query**

In `persistence/repository.py`, add near `get_faction_mission_completion_counts`:

```python
    def get_session_activity_report(self, since: str) -> dict:
        """{system_name: {faction_name: {"missions": {...}, "combat_bonds_total": int,
        "cz_kills": {...}, "trade_sold": {...}}}} -- everything since the last
        detected BGS tick (see edc/core/bgs_tick.py), across every system,
        not scoped to one faction (unlike the Faction Expansion tracker's
        get_faction_mission_completion_counts). Four small queries
        assembled in Python rather than one JOIN -- the four event types
        don't share a natural join key beyond system+faction, and a JOIN
        would multiply rows across tables instead of aggregating them.
        A system_address with no systems row (can't be named) is skipped."""
        names = {
            r["system_address"]: r["system_name"]
            for r in self.db.execute("SELECT system_address, system_name FROM systems").fetchall()
            if r["system_name"]
        }

        def _bucket(system_address: int, faction_name: str) -> dict:
            system_name = names.get(system_address)
            if system_name is None:
                return None
            report.setdefault(system_name, {})
            return report[system_name].setdefault(faction_name, {
                "missions": {"count": 0, "weighted": 0, "primary_count": 0, "secondary_count": 0},
                "combat_bonds_total": 0,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
                "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0},
            })

        report: dict = {}

        mission_rows = self.db.execute(
            "SELECT system_address, faction_name, influence_tier, is_primary "
            "FROM faction_mission_completions WHERE completed_at >= ?",
            (since,),
        ).fetchall()
        for r in mission_rows:
            entry = _bucket(r["system_address"], r["faction_name"])
            if entry is None:
                continue
            m = entry["missions"]
            m["count"] += 1
            if isinstance(r["influence_tier"], str):
                m["weighted"] += len(r["influence_tier"])
            if r["is_primary"]:
                m["primary_count"] += 1
            else:
                m["secondary_count"] += 1

        for r in self.get_faction_combat_bonds_since(since):
            entry = _bucket(r["system_address"], r["faction_name"])
            if entry is None:
                continue
            entry["combat_bonds_total"] += r["reward"]

        for r in self.get_faction_cz_kills_since(since):
            entry = _bucket(r["system_address"], r["faction_name"])
            if entry is None:
                continue
            key = f"{r['zone_type']}_{r['size']}"
            if key in entry["cz_kills"]:
                entry["cz_kills"][key] += 1

        for r in self.get_faction_trade_sold_since(since):
            entry = _bucket(r["system_address"], r["faction_name"])
            if entry is None:
                continue
            if r["kind"] in entry["trade_sold"]:
                entry["trade_sold"][r["kind"]] += r["value"]

        return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_report.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add persistence/repository.py tests/test_session_activity_report.py
git commit -m "feat: aggregate all-faction session BGS activity into one report query"
```

---

### Task 5: `event_engine.py` — expose the CZ-kill credit for the current event

**Files:**
- Modify: `edc/core/event_engine.py:363-403` (`_credit_cz_kill`), and `edc/core/state.py` (add one new field)
- Modify: `edc/core/event_engine.py`'s `FactionKillBond` handler (around line 1000-1038) to reset the new field
- Test: `tests/test_event_engine_cz_kill_credit.py` (new file)

**Interfaces:**
- Produces: `state.last_cz_credit: Optional[dict]` — `{"faction_name": str, "zone_type": "ground"|"space", "size": "l"|"m"|"h"}` when `_credit_cz_kill` just applied a NEW tally increment for the event currently being processed, else `None`. Consumed by Task 6's `_record_faction_cz_kill` (reads it once, right after `engine.process()`, alongside `self.state.system_address` and the event's own `timestamp`).

**Why this is needed:** `_credit_cz_kill` already tallies CZ kills into `state.cz_kills[faction_name]`, but that's a cumulative dict — main_window.py can't tell from it alone whether *this* `FactionKillBond` just added a new kill (vs. was a duplicate/non-CZ bond). `last_cz_credit` is a one-shot "here's what just happened" signal, reset to `None` at the top of every `FactionKillBond`'s handling and only set when `_credit_cz_kill` actually increments a tally.

- [ ] **Step 1: Write the failing test**

Create `tests/test_event_engine_cz_kill_credit.py`:

```python
"""EventEngine's FactionKillBond handling sets state.last_cz_credit
exactly when _credit_cz_kill applies a new tally increment -- a one-shot
signal main_window.py reads right after engine.process() to persist the
credit for the session BGS activity report (the cumulative
state.cz_kills dict alone can't tell a caller whether THIS event just
added a new kill). Real EventEngine, same construction and SupercruiseExit
trigger as test_active_combat_bonds.py's sibling in-memory-tally tests."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _bond_event(reward, awarding_faction="Elite United Worlds", ts="2026-09-25T10:00:00Z"):
    return {
        "event": "FactionKillBond", "timestamp": ts, "Reward": reward,
        "AwardingFaction": awarding_faction, "VictimFaction": "Rival Faction",
    }


def _enter_space_cz(engine, size_suffix="High", ts="2026-09-25T09:59:00Z"):
    engine.process({
        "event": "SupercruiseExit", "timestamp": ts,
        "Type": f"$Warzone_PointRace_{size_suffix};", "StarSystem": "Ekono", "SystemAddress": 12345,
    })


def test_last_cz_credit_is_set_when_a_space_cz_kill_is_confirmed(tmp_path):
    engine = _engine(tmp_path)
    _enter_space_cz(engine, "High")
    state, _ = engine.process(_bond_event(50000))
    assert state.last_cz_credit == {
        "faction_name": "Elite United Worlds", "zone_type": "space", "size": "h",
    }


def test_last_cz_credit_is_none_when_no_pending_cz_window(tmp_path):
    engine = _engine(tmp_path)
    state, _ = engine.process(_bond_event(50000))
    assert state.last_cz_credit is None


def test_last_cz_credit_resets_between_events(tmp_path):
    engine = _engine(tmp_path)
    _enter_space_cz(engine, "High")
    state, _ = engine.process(_bond_event(50000, ts="2026-09-25T10:00:00Z"))
    assert state.last_cz_credit is not None
    state, _ = engine.process(_bond_event(50000, ts="2026-09-25T10:05:00Z"))  # no fresh pending CZ this time
    assert state.last_cz_credit is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_event_engine_cz_kill_credit.py -v`
Expected: FAIL with `AttributeError: 'GameState' object has no attribute 'last_cz_credit'`

- [ ] **Step 3: Add the state field**

In `edc/core/state.py`, add near `cz_kills` (around line 294):

```python
    last_cz_credit: Optional[dict] = None  # one-shot signal for the current event -- see _credit_cz_kill
```

- [ ] **Step 4: Reset and set the field in `event_engine.py`**

In `edc/core/event_engine.py`, at the top of the `elif name == "FactionKillBond":` block (around line 1000), add the reset as the first line:

```python
        elif name == "FactionKillBond":
            self.state.last_cz_credit = None
            credit_massacre_kill(self.state.active_missions, event.get("VictimFaction"), self.state.system)
```

In `_credit_cz_kill` (around line 363-403), set `last_cz_credit` at each of the two places a tally increment actually happens. For the ground/settlement branch (after `pending_settlement["size"] = new_size`, around line 394):

```python
                pending_settlement["size"] = new_size
                self.state.last_cz_credit = {"faction_name": faction_name, "zone_type": "ground", "size": new_size}
```

For the space branch (after `tally[f"space_{size}"] = ...`, around line 403):

```python
                tally[f"space_{size}"] = tally.get(f"space_{size}", 0) + 1
                self.state.last_cz_credit = {"faction_name": faction_name, "zone_type": "space", "size": size}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_event_engine_cz_kill_credit.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full existing CZ-kill test suite to confirm no regression**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q -k "cz_kill"`
Expected: all passing (no change to existing tally behavior, only a new field added)

- [ ] **Step 7: Commit**

```bash
git add edc/core/state.py edc/core/event_engine.py tests/test_event_engine_cz_kill_credit.py
git commit -m "feat: expose a one-shot CZ-kill-credit signal for the current event"
```

---

### Task 6: `main_window.py` hooks — combat bonds, CZ kills, trade sold

**Files:**
- Modify: `edc/ui/main_window.py` (add three new methods near `_record_faction_mission_completion`, wire into `_on_event`)
- Test: `tests/test_record_session_activity_events.py` (new file)

**Interfaces:**
- Consumes: `Repository.record_faction_combat_bond` (Task 1), `Repository.record_faction_cz_kill` (Task 2), `Repository.record_faction_trade_sold` (Task 3), `state.last_cz_credit` (Task 5).
- Produces: `MainWindow._record_faction_combat_bond(evt: dict) -> None`, `MainWindow._record_faction_cz_kill(evt: dict) -> None`, `MainWindow._record_faction_trade_sold(evt: dict) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_record_session_activity_events.py`:

```python
"""MainWindow._record_faction_combat_bond / _record_faction_cz_kill /
_record_faction_trade_sold -- feed the three new session-activity tables
from their respective journal events. Fake self, same pattern as
test_record_faction_mission_completion.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345, last_cz_credit=None):
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address, last_cz_credit=last_cz_credit),
        repo=SimpleNamespace(
            record_faction_combat_bond=lambda **kw: saved.append(("bond", kw)),
            record_faction_cz_kill=lambda **kw: saved.append(("cz", kw)),
            record_faction_trade_sold=lambda **kw: saved.append(("trade", kw)),
        ),
        _saved=saved,
    )


# --- combat bonds ---

def test_combat_bond_is_recorded():
    fake_self = _fake_self()
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == [("bond", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "reward": 15000, "earned_at": "2026-09-25T10:00:00Z",
    })]


def test_combat_bond_skipped_without_awarding_faction():
    fake_self = _fake_self()
    evt = {"event": "FactionKillBond", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == []


def test_combat_bond_skipped_without_system_address():
    fake_self = _fake_self(system_address=None)
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == []


# --- CZ kills ---

def test_cz_kill_is_recorded_when_last_cz_credit_is_set():
    fake_self = _fake_self(last_cz_credit={"faction_name": "Elite United Worlds", "zone_type": "space", "size": "h"})
    evt = {"event": "FactionKillBond", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_cz_kill(fake_self, evt)
    assert fake_self._saved == [("cz", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "zone_type": "space", "size": "h", "earned_at": "2026-09-25T10:00:00Z",
    })]


def test_cz_kill_skipped_when_last_cz_credit_is_none():
    fake_self = _fake_self(last_cz_credit=None)
    evt = {"event": "FactionKillBond", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_cz_kill(fake_self, evt)
    assert fake_self._saved == []


# --- trade/exploration/exobiology sold ---

def test_market_sell_is_recorded_as_commodity():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "commodity", "value": 63085, "sold_at": "2026-09-25T10:00:00Z",
    })]


def test_multi_sell_exploration_data_is_recorded_as_exploration():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "MultiSellExplorationData", "BaseValue": 1450787, "Bonus": 0,
           "TotalEarnings": 1305717, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "exploration", "value": 1305717, "sold_at": "2026-09-25T10:00:00Z",
    })]


def test_legacy_sell_exploration_data_falls_back_to_base_plus_bonus():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "SellExplorationData", "BaseValue": 5000, "Bonus": 500, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "exploration", "value": 5500, "sold_at": "2026-09-25T10:00:00Z",
    })]


def test_sell_organic_data_sums_biodata_as_exobiology():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {
        "event": "SellOrganicData", "timestamp": "2026-09-25T10:00:00Z",
        "BioData": [
            {"Species": "Fonticulua Digitos", "Value": 1804100, "Bonus": 0},
            {"Species": "Some Other Species", "Value": 200000, "Bonus": 50000},
        ],
    }
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "exobiology", "value": 2054100, "sold_at": "2026-09-25T10:00:00Z",
    })]


def test_trade_sold_skipped_without_controlling_faction():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = None
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_record_session_activity_events.py -v`
Expected: FAIL with `AttributeError: type object 'MainWindow' has no attribute '_record_faction_combat_bond'`

- [ ] **Step 3: Implement the three methods**

In `edc/ui/main_window.py`, add near `_record_faction_mission_completion`:

```python
    def _record_faction_combat_bond(self, evt: dict) -> None:
        """FactionKillBond carries AwardingFaction directly -- unlike
        Bounty (which only carries VictimFaction, the faction actually
        credited is determined later, at redemption, not at kill time),
        so only FactionKillBond feeds the session activity report's
        combat-bond total."""
        faction_name = evt.get("AwardingFaction")
        reward = evt.get("Reward")
        system_address = getattr(self.state, "system_address", None)
        if not (isinstance(faction_name, str) and faction_name and isinstance(reward, int)
                and isinstance(system_address, int)):
            return
        from datetime import datetime, timezone
        try:
            self.repo.record_faction_combat_bond(
                system_address=system_address, faction_name=faction_name, reward=reward,
                earned_at=evt.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            log.exception("Failed to record faction combat bond")

    def _record_faction_cz_kill(self, evt: dict) -> None:
        """state.last_cz_credit is a one-shot signal set by
        event_engine.py's _credit_cz_kill only when THIS FactionKillBond
        just confirmed a new CZ kill (None otherwise -- e.g. a plain
        combat bond outside any pending-CZ window)."""
        credit = getattr(self.state, "last_cz_credit", None)
        system_address = getattr(self.state, "system_address", None)
        if not (isinstance(credit, dict) and isinstance(system_address, int)):
            return
        from datetime import datetime, timezone
        try:
            self.repo.record_faction_cz_kill(
                system_address=system_address, faction_name=credit["faction_name"],
                zone_type=credit["zone_type"], size=credit["size"],
                earned_at=evt.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            log.exception("Failed to record faction CZ kill")

    def _record_faction_trade_sold(self, evt: dict) -> None:
        """Commodity (MarketSell), exploration data (SellExplorationData/
        MultiSellExplorationData), and exobiology (SellOrganicData) sales
        all happen while docked, so the current system's controlling
        faction at sale time (state.controlling_faction) is who gets
        credited -- same assumption _at_squadron_faction_station() already
        makes for the existing squadron_bgs_trade_cr lump total."""
        name = evt.get("event")
        faction_name = getattr(self.state, "controlling_faction", None)
        system_address = getattr(self.state, "system_address", None)
        if not (isinstance(faction_name, str) and faction_name and isinstance(system_address, int)):
            return

        if name == "MarketSell":
            value = evt.get("TotalSale")
            kind = "commodity"
        elif name == "MultiSellExplorationData":
            value = evt.get("TotalEarnings")
            if not isinstance(value, int):
                base = evt.get("BaseValue") or 0
                bonus = evt.get("Bonus") or 0
                value = base + bonus if isinstance(base, int) and isinstance(bonus, int) else None
            kind = "exploration"
        elif name == "SellExplorationData":
            base = evt.get("BaseValue")
            bonus = evt.get("Bonus")
            value = base + bonus if isinstance(base, int) and isinstance(bonus, int) else None
            kind = "exploration"
        elif name == "SellOrganicData":
            bio_data = evt.get("BioData")
            value = None
            if isinstance(bio_data, list):
                value = sum(
                    (item.get("Value") or 0) + (item.get("Bonus") or 0)
                    for item in bio_data if isinstance(item, dict)
                )
            kind = "exobiology"
        else:
            return

        if not isinstance(value, int):
            return

        from datetime import datetime, timezone
        try:
            self.repo.record_faction_trade_sold(
                system_address=system_address, faction_name=faction_name, kind=kind, value=value,
                sold_at=evt.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            log.exception("Failed to record faction trade sold")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_record_session_activity_events.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Wire the three methods into `_on_event`**

In `edc/ui/main_window.py`'s `_on_event`, find the existing dispatch line:

```python
        if name == "MissionCompleted":
            self._record_faction_mission_completion(evt)
```

Add immediately after it:

```python
        if name == "FactionKillBond":
            self._record_faction_combat_bond(evt)
            self._record_faction_cz_kill(evt)

        if name in ("MarketSell", "MultiSellExplorationData", "SellExplorationData", "SellOrganicData"):
            self._record_faction_trade_sold(evt)
```

- [ ] **Step 6: Syntax-check and run the full test suite**

Run: `./.venv/Scripts/python.exe -m py_compile edc/ui/main_window.py`
Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all passing (aside from any pre-existing unrelated failures already present before this plan started — confirm via `git stash` if any new failure appears, per this project's established verification pattern)

- [ ] **Step 7: Commit**

```bash
git add edc/ui/main_window.py tests/test_record_session_activity_events.py
git commit -m "feat: wire combat bond, CZ kill, and trade-sold events into the session activity report"
```

---

### Task 7: `SessionActivityDialog` panel

**Files:**
- Create: `edc/ui/panels/session_activity_dialog.py`
- Test: `tests/test_session_activity_dialog_render.py` (new file)

**Interfaces:**
- Consumes: `Repository.get_session_activity_report(since)` (Task 4), `PlayerFactionPanel._latest_known_tick` (existing, already kept fresh by `_BgsTickCheckWorker`/`_on_bgs_tick_check_tick` in `main_window.py`), `PlayerFactionPanel._repo` (existing attribute).
- Produces: `SessionActivityDialog(QDialog)` with `__init__(self, panel: "PlayerFactionPanel")`, a public `refresh(self) -> None` method that re-reads the tick and re-queries, and `showEvent` that calls `refresh()` (same refresh-on-open convention as `FactionExpansionDialog`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_session_activity_dialog_render.py`:

```python
"""SessionActivityDialog._render_report() -- pure formatting logic taking
an already-fetched report dict, kept separate from refresh() (which does
the tick fetch + DB query) so it's testable without Qt/DB setup. Fake
self carrying only the widgets _render_report() touches, same pattern as
test_faction_expansion_live_push.py's _fake_expansion_dialog."""
from types import SimpleNamespace

from edc.ui.panels.session_activity_dialog import SessionActivityDialog


def _fake_dialog():
    rendered = []
    return SimpleNamespace(_set_body_text=lambda text: rendered.append(text)), rendered


def test_empty_report_shows_a_no_activity_message():
    fs, rendered = _fake_dialog()
    SessionActivityDialog._render_report(fs, {})
    assert "No activity" in rendered[0]


def test_report_lists_system_and_faction_with_mission_counts():
    fs, rendered = _fake_dialog()
    report = {
        "Ekono": {
            "Elite United Worlds": {
                "missions": {"count": 3, "weighted": 6, "primary_count": 2, "secondary_count": 1},
                "combat_bonds_total": 20000,
                "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2},
                "trade_sold": {"commodity": 63085, "exploration": 0, "exobiology": 0},
            },
        },
    }
    SessionActivityDialog._render_report(fs, report)
    text = rendered[0]
    assert "Ekono" in text
    assert "Elite United Worlds" in text
    assert "3" in text  # mission count
    assert "20,000" in text  # combat bonds total, thousands-separated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_dialog_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'edc.ui.panels.session_activity_dialog'`

- [ ] **Step 3: Implement the dialog**

Create `edc/ui/panels/session_activity_dialog.py`:

```python
# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Session BGS Activity Report — read-only window showing every faction's
mission/combat/CZ/trade activity, grouped by system, since the last
detected BGS tick, across every system visited — not scoped to one
target faction the way the Faction Expansion tracker is (that one stays
exactly as-is; this is a different question, "what did I do this
session" vs. "is my one targeted push working").

Session boundary reuses PlayerFactionPanel._latest_known_tick (already
kept fresh by main_window.py's _BgsTickCheckWorker timer) rather than
fetching the tick itself -- no new network code needed.
"""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

from edc.ui.style import HDR_STYLE as _HDR_STYLE
from edc.ui import formatting as fmt

log = logging.getLogger("edc.session_activity")


class SessionActivityDialog(QDialog):
    """Non-modal window: whole-session, all-faction BGS activity report."""

    def __init__(self, panel: "PlayerFactionPanel"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self.setWindowTitle("Session BGS Activity Report")
        self.resize(700, 600)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel("SESSION ACTIVITY — SINCE LAST BGS TICK")
        hdr.setStyleSheet(_HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        self._tick_label = QLabel("")
        self._tick_label.setStyleSheet("background:transparent; border:none; color:#888888; font-size:11px;")
        layout.addWidget(self._tick_label)

        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setStyleSheet("background:#0d1520; border:1px solid #223; color:#c8c8c8;")
        layout.addWidget(self._body, 1)

    def _set_body_text(self, text: str) -> None:
        self._body.setPlainText(text)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        tick_iso = getattr(self._panel, "_latest_known_tick", None)
        if not tick_iso:
            self._tick_label.setText("No BGS tick detected yet this session — showing all recorded activity.")
            since = "1970-01-01T00:00:00Z"
        else:
            age_txt, _ = fmt.relative_time(tick_iso)
            self._tick_label.setText(f"Since last tick: {age_txt}")
            since = tick_iso

        try:
            report = self._panel._repo.get_session_activity_report(since)
        except Exception:
            log.exception("Failed to load session activity report")
            report = {}
        self._render_report(report)

    def _render_report(self, report: dict) -> None:
        if not report:
            self._set_body_text("No activity recorded yet this session.")
            return

        lines = []
        for system_name in sorted(report.keys()):
            lines.append(f"=== {system_name} ===")
            factions = report[system_name]
            for faction_name in sorted(factions.keys()):
                entry = factions[faction_name]
                lines.append(f"  [{faction_name}]")
                m = entry["missions"]
                if m["count"]:
                    lines.append(
                        f"    Missions: {m['count']} (weight {m['weighted']}) — "
                        f"{m['primary_count']} primary / {m['secondary_count']} secondary"
                    )
                if entry["combat_bonds_total"]:
                    lines.append(f"    Combat bonds: {entry['combat_bonds_total']:,}")
                cz = entry["cz_kills"]
                cz_total = sum(cz.values())
                if cz_total:
                    parts = [f"{v}x {k}" for k, v in cz.items() if v]
                    lines.append(f"    CZ kills: {', '.join(parts)}")
                trade = entry["trade_sold"]
                trade_total = sum(trade.values())
                if trade_total:
                    parts = [f"{k}: {v:,}" for k, v in trade.items() if v]
                    lines.append(f"    Sold: {', '.join(parts)}")
            lines.append("")

        self._set_body_text("\n".join(lines))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_dialog_render.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Syntax-check**

Run: `./.venv/Scripts/python.exe -m py_compile edc/ui/panels/session_activity_dialog.py`
Expected: no output (success)

- [ ] **Step 6: Commit**

```bash
git add edc/ui/panels/session_activity_dialog.py tests/test_session_activity_dialog_render.py
git commit -m "feat: add the Session BGS Activity Report dialog"
```

---

### Task 8: Launch button on `PlayerFactionPanel`

**Files:**
- Modify: `edc/ui/panels/player_faction_panel.py` (add button next to "Faction Expansion Tracker…", mirroring `_open_faction_expansion_dialog`'s exact shape at line 1932-1937)
- Test: `tests/test_session_activity_dialog_launch.py` (new file)

**Interfaces:**
- Consumes: `SessionActivityDialog` (Task 7).
- Produces: `PlayerFactionPanel._open_session_activity_dialog(self) -> None`, `PlayerFactionPanel._session_activity_dialog: Optional[SessionActivityDialog]` (instance attribute, initialized `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_session_activity_dialog_launch.py`:

```python
"""PlayerFactionPanel._open_session_activity_dialog() -- lazily creates
the SessionActivityDialog once, reuses it on subsequent opens. Fake
self + a fake dialog class (avoids constructing a real QDialog), same
pattern as test_faction_expansion_live_push.py."""
from types import SimpleNamespace

from edc.ui.panels.player_faction_panel import PlayerFactionPanel


def _fake_dialog_cls():
    instances = []

    class _FakeDialog:
        def __init__(self, panel):
            self.panel = panel
            self.shown = False
            self.raised = False
            self.activated = False
            instances.append(self)

        def show(self):
            self.shown = True

        def raise_(self):
            self.raised = True

        def activateWindow(self):
            self.activated = True

    return _FakeDialog, instances


def test_creates_the_dialog_on_first_open(monkeypatch):
    fake_cls, instances = _fake_dialog_cls()
    monkeypatch.setattr("edc.ui.panels.player_faction_panel.SessionActivityDialog", fake_cls)
    fake_self = SimpleNamespace(_session_activity_dialog=None)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    assert len(instances) == 1
    assert instances[0].shown and instances[0].raised and instances[0].activated
    assert fake_self._session_activity_dialog is instances[0]


def test_reuses_the_dialog_on_second_open(monkeypatch):
    fake_cls, instances = _fake_dialog_cls()
    monkeypatch.setattr("edc.ui.panels.player_faction_panel.SessionActivityDialog", fake_cls)
    fake_self = SimpleNamespace(_session_activity_dialog=None)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    PlayerFactionPanel._open_session_activity_dialog(fake_self)
    assert len(instances) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_dialog_launch.py -v`
Expected: FAIL with `AttributeError: type object 'PlayerFactionPanel' has no attribute '_open_session_activity_dialog'`

- [ ] **Step 3: Import the dialog and add the instance attribute**

In `edc/ui/panels/player_faction_panel.py`, find the existing import of `FactionExpansionDialog` (near the top of the file) and add alongside it:

```python
from edc.ui.panels.session_activity_dialog import SessionActivityDialog
```

Find `self._faction_expansion_dialog = None` (line 658) and add immediately after:

```python
        self._session_activity_dialog = None
```

- [ ] **Step 4: Add the button next to "Faction Expansion Tracker…"**

Find the `expansion_btn` block (around line 808-819) and add immediately after `refresh_row.addWidget(expansion_btn)`:

```python
        session_activity_btn = QPushButton("Session Activity Report…")
        session_activity_btn.setStyleSheet(
            "QPushButton { background:#1a1a3a; color:#B0A0FF; border:1px solid #3a3a6a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a2a5a; }"
        )
        session_activity_btn.setToolTip(
            "Every faction's mission/combat/CZ/trade activity, grouped by system, since the "
            "last detected BGS tick -- across every system visited, not just one target."
        )
        session_activity_btn.clicked.connect(self._open_session_activity_dialog)
        refresh_row.addWidget(session_activity_btn)
```

- [ ] **Step 5: Implement `_open_session_activity_dialog`**

Add near `_open_faction_expansion_dialog` (line 1932-1937):

```python
    def _open_session_activity_dialog(self) -> None:
        if self._session_activity_dialog is None:
            self._session_activity_dialog = SessionActivityDialog(self)
        self._session_activity_dialog.show()
        self._session_activity_dialog.raise_()
        self._session_activity_dialog.activateWindow()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_session_activity_dialog_launch.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Syntax-check and run the full test suite**

Run: `./.venv/Scripts/python.exe -m py_compile edc/ui/panels/player_faction_panel.py`
Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all passing (aside from any pre-existing unrelated failures already present before this plan started)

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/player_faction_panel.py tests/test_session_activity_dialog_launch.py
git commit -m "feat: launch the Session BGS Activity Report from the Player Faction tab"
```

---

### Task 9: Live verification

**Files:** none (manual verification only)

- [ ] **Step 1: Launch the app and open the new report**

Run the app (per this project's own run instructions), open the Player Faction tab, click "Session Activity Report…". Confirm the window opens without error and shows "No activity recorded yet this session" (or real data, if any of the new events have already fired since the plan's tables were created).

- [ ] **Step 2: Generate real activity and confirm it appears**

In-game, complete a mission for any faction, or earn a FactionKillBond (including inside a conflict zone), or sell cargo/exploration/exobiology data at a station. Click "Refresh" on the report. Confirm the relevant system/faction/category now shows the new activity with correct numbers (cross-check the combat bond reward, CZ kill size, or sale value against the actual journal event, same verification approach used earlier this session for the Faction Expansion tracker fixes).

- [ ] **Step 3: Confirm tick-boundary filtering**

If a BGS tick has been detected this session (check the existing tick countdown display elsewhere in the app), confirm the report's "Since last tick" label shows a sensible age, and that activity from before that tick (if any old rows exist in the DB from testing) does not appear.

- [ ] **Step 4: Report results**

Report what was confirmed and what wasn't back to the user before considering this plan complete — per this project's own testing convention (confirmation means working in-game or visually confirmed in the running app, not just green tests).
