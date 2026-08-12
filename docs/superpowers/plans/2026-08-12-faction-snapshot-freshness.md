# Faction Snapshot Freshness Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `faction_snapshots` writes freshness-aware — only overwrite an existing row when the incoming data is actually more recent than what's stored, using each pipeline's real data timestamp instead of wall-clock write order.

**Architecture:** Two new columns (`data_timestamp`, `source`) added via the existing flat-migration-list pattern. A new normalization helper converts every pipeline's differently-shaped timestamp (EDSM's Unix epoch, journal's `...Z`-suffixed ISO string) into one consistent string format so SQL can compare them lexically and get the right chronological answer. The upsert in `save_faction_snapshot()` gains a `WHERE` guard on its `DO UPDATE` so a stale write can no longer silently clobber a fresher one already in the table. All five existing write call sites are updated to supply real values instead of nothing.

**Tech Stack:** Python, SQLite (via the existing `Database`/`Repository` classes), pytest.

## Global Constraints

- `data_timestamp` must be normalized to exactly `"YYYY-MM-DDTHH:MM:SSZ"` before storage — mixing `Z`-suffix and `+00:00`-suffix strings for the same instant would sort incorrectly under lexical string comparison (`Z` is ASCII 90, `+` is ASCII 43).
- `save_faction_snapshot()`'s two new parameters (`data_timestamp`, `source`) are explicit, required, positional-or-keyword arguments — not smuggled through the `faction` dict — matching how `is_controlling`/`snapshot_date` already work as explicit parameters today.
- Pre-existing rows have `NULL` in the new columns after migration — the upsert's `WHERE` guard must treat `NULL` as "always losable" so the next real write from any pipeline backfills them naturally. No backfill/migration script.
- `source` is one of exactly `"journal"`, `"edsm"`, `"eddn"`, `"csv"` — no other values.
- No test for individual call-site plumbing (reading `evt.get("timestamp")`, `row.get("updated_date")`, etc.) — matches this codebase's existing convention of testing pure logic directly and verifying UI/event wiring live.

---

### Task 1: Schema migration

**Files:**
- Modify: `persistence/database.py`

**Interfaces:**
- Produces: `faction_snapshots.data_timestamp` (TEXT, nullable) and `faction_snapshots.source` (TEXT, nullable) columns, available to Task 2.

No automated test for this task — matches this file's existing convention (the sibling `ALTER TABLE faction_snapshots ADD COLUMN my_reputation REAL` migration has none either).

- [ ] **Step 1: Add the two new columns**

In `persistence/database.py`, find the existing migration list entries (around line 122-123):

```python
            "ALTER TABLE faction_snapshots ADD COLUMN my_reputation REAL",
            "ALTER TABLE faction_snapshots ADD COLUMN is_squadron_faction INTEGER DEFAULT 0",
```

Add two new lines directly after them, in the same list:

```python
            "ALTER TABLE faction_snapshots ADD COLUMN my_reputation REAL",
            "ALTER TABLE faction_snapshots ADD COLUMN is_squadron_faction INTEGER DEFAULT 0",
            "ALTER TABLE faction_snapshots ADD COLUMN data_timestamp TEXT",
            "ALTER TABLE faction_snapshots ADD COLUMN source TEXT",
```

- [ ] **Step 2: Compile-check**

Run: `python -m py_compile persistence/database.py`
Expected: no output (success)

- [ ] **Step 3: Commit**

```bash
git add persistence/database.py
git commit -m "feat: add data_timestamp and source columns to faction_snapshots"
```

---

### Task 2: Freshness-guarded upsert

**Files:**
- Modify: `persistence/repository.py`
- Test: `tests/test_faction_snapshot_freshness.py`

**Interfaces:**
- Consumes: `faction_snapshots.data_timestamp`/`.source` columns (Task 1).
- Produces: `_normalize_data_timestamp(value) -> str` (module-level function in `persistence/repository.py`, accepts a Unix epoch int/float or an ISO8601 string with `Z` or `+00:00` suffix, returns `"YYYY-MM-DDTHH:MM:SSZ"`). `Repository.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, data_timestamp, source)` — two new required parameters after the existing four.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_snapshot_freshness.py`:

```python
"""Tests for save_faction_snapshot()'s freshness-guarded upsert and its
_normalize_data_timestamp() helper -- real SQLite (temp file), not mocks,
since the guard lives in the SQL itself."""
import pytest

from persistence.database import Database
from persistence.repository import Repository, _normalize_data_timestamp


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.run_migrations()
    return Repository(db)


def _faction(name="Test Faction", influence=0.5):
    return {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}


def _read_row(repo, system_address, faction_name, snapshot_date):
    row = repo.db.conn.execute(
        "SELECT * FROM faction_snapshots WHERE system_address = ? AND faction_name = ? AND snapshot_date = ?",
        (system_address, faction_name, snapshot_date),
    ).fetchone()
    return dict(row) if row else None


# --- _normalize_data_timestamp() ---

def test_normalize_handles_z_suffix_string():
    assert _normalize_data_timestamp("2026-08-12T09:18:35Z") == "2026-08-12T09:18:35Z"


def test_normalize_handles_offset_suffix_string():
    assert _normalize_data_timestamp("2026-08-12T09:18:35+00:00") == "2026-08-12T09:18:35Z"


def test_normalize_handles_unix_epoch():
    # 1786547694 -- confirmed live from a real EDSM lastUpdate value this session;
    # expected value independently verified via datetime.fromtimestamp(1786547694, tz=timezone.utc)
    assert _normalize_data_timestamp(1786547694) == "2026-08-12T15:14:54Z"


def test_normalize_z_and_epoch_agree_for_the_same_instant():
    epoch = 1786547694
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _normalize_data_timestamp(epoch) == _normalize_data_timestamp(iso)


def test_normalize_falls_back_to_now_for_missing_value():
    from datetime import datetime, timezone
    before = datetime.now(timezone.utc)
    result = _normalize_data_timestamp(None)
    after = datetime.now(timezone.utc)
    # Just confirm it's a valid, well-formed recent timestamp, not a crash.
    parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= parsed <= after or (after - parsed).total_seconds() < 2


# --- save_faction_snapshot()'s freshness guard ---

def test_fresher_write_overwrites_older_row(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    repo.save_faction_snapshot(1, _faction(influence=0.7), "2026-08-12", False, "2026-08-12T12:00:00Z", "eddn")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.7
    assert row["source"] == "eddn"
    assert row["data_timestamp"] == "2026-08-12T12:00:00Z"


def test_staler_write_does_not_overwrite_newer_row(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.7), "2026-08-12", False, "2026-08-12T12:00:00Z", "eddn")
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.7  # unchanged -- the older write was rejected
    assert row["source"] == "eddn"


def test_equal_timestamp_write_does_overwrite(repo):
    repo.save_faction_snapshot(1, _faction(influence=0.3), "2026-08-12", False, "2026-08-12T09:00:00Z", "edsm")
    repo.save_faction_snapshot(1, _faction(influence=0.4), "2026-08-12", False, "2026-08-12T09:00:00Z", "journal")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.4


def test_any_write_overwrites_a_legacy_null_timestamp_row(repo):
    # Simulate a pre-migration row: insert directly, bypassing the
    # timestamp-aware method entirely, leaving data_timestamp NULL.
    repo.db.conn.execute(
        """INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date, influence, is_controlling)
           VALUES (?, ?, ?, ?, ?)""",
        (1, "Test Faction", "2026-08-12", 0.1, 0),
    )
    repo.db.conn.commit()
    repo.save_faction_snapshot(1, _faction(influence=0.9), "2026-08-12", False, "2026-08-12T01:00:00Z", "edsm")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["influence"] == 0.9
    assert row["data_timestamp"] == "2026-08-12T01:00:00Z"


def test_source_and_data_timestamp_are_stored_on_first_write(repo):
    repo.save_faction_snapshot(1, _faction(), "2026-08-12", True, "2026-08-12T09:18:35Z", "csv")
    row = _read_row(repo, 1, "Test Faction", "2026-08-12")
    assert row["source"] == "csv"
    assert row["data_timestamp"] == "2026-08-12T09:18:35Z"
    assert row["is_controlling"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_faction_snapshot_freshness.py -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_data_timestamp'`

- [ ] **Step 3: Implement `_normalize_data_timestamp()` and update `save_faction_snapshot()`**

Add to `persistence/repository.py`, directly before `save_faction_snapshot()` (which starts around line 301):

```python
def _normalize_data_timestamp(value) -> str:
    """Normalizes an EDSM Unix epoch (int/float) or an ISO8601 string
    (with a 'Z' or '+00:00' suffix) into one consistent
    "YYYY-MM-DDTHH:MM:SSZ" string, so lexical string comparison in SQL
    sorts chronologically correctly regardless of which pipeline
    produced the value -- otherwise a 'Z' and a '+00:00' suffix on the
    same real instant would compare unequal/out of order, since 'Z'
    (ASCII 90) and '+' (ASCII 43) differ as characters. Falls back to
    "now" (UTC) if the input is missing or unparseable, rather than
    storing an unusable value that would always lose the freshness
    comparison."""
    from datetime import datetime, timezone

    dt = None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str) and value.strip():
            ts = value.strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OSError):
        dt = None

    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
```

Then change `save_faction_snapshot()`'s signature and body. Current signature:

```python
    def save_faction_snapshot(
        self,
        system_address: int,
        faction: dict,
        snapshot_date: str,
        is_controlling: bool,
    ):
```

New signature:

```python
    def save_faction_snapshot(
        self,
        system_address: int,
        faction: dict,
        snapshot_date: str,
        is_controlling: bool,
        data_timestamp: str,
        source: str,
    ):
```

Current SQL (starts a few lines into the method body):

```python
        self.db.execute(
            """
            INSERT INTO faction_snapshots (
                system_address, faction_name, snapshot_date,
                influence, government, allegiance, faction_state, happiness,
                active_states, pending_states, recovering_states, is_controlling,
                my_reputation, is_squadron_faction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, faction_name, snapshot_date) DO UPDATE SET
                influence           = excluded.influence,
                government          = excluded.government,
                allegiance          = excluded.allegiance,
                faction_state       = excluded.faction_state,
                happiness           = excluded.happiness,
                active_states       = excluded.active_states,
                pending_states      = excluded.pending_states,
                recovering_states   = excluded.recovering_states,
                is_controlling      = excluded.is_controlling,
                my_reputation       = excluded.my_reputation,
                is_squadron_faction = excluded.is_squadron_faction
            """,
            (
                system_address,
                name,
                snapshot_date,
                float(influence) if isinstance(influence, (int, float)) else None,
                faction.get("Government"),
                faction.get("Allegiance"),
                faction.get("FactionState"),
                faction.get("Happiness_Localised") or faction.get("Happiness"),
                json.dumps(faction.get("ActiveStates")) if faction.get("ActiveStates") else None,
                json.dumps(faction.get("PendingStates")) if faction.get("PendingStates") else None,
                json.dumps(faction.get("RecoveringStates")) if faction.get("RecoveringStates") else None,
                1 if is_controlling else 0,
                float(my_reputation) if isinstance(my_reputation, (int, float)) else None,
                1 if is_squadron_faction else 0,
            ),
        )
```

New SQL — adds `data_timestamp`/`source` to the column list, `VALUES`, `DO UPDATE SET`, params tuple, and adds the `WHERE` guard:

```python
        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO faction_snapshots (
                system_address, faction_name, snapshot_date,
                influence, government, allegiance, faction_state, happiness,
                active_states, pending_states, recovering_states, is_controlling,
                my_reputation, is_squadron_faction, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, faction_name, snapshot_date) DO UPDATE SET
                influence           = excluded.influence,
                government          = excluded.government,
                allegiance          = excluded.allegiance,
                faction_state       = excluded.faction_state,
                happiness           = excluded.happiness,
                active_states       = excluded.active_states,
                pending_states      = excluded.pending_states,
                recovering_states   = excluded.recovering_states,
                is_controlling      = excluded.is_controlling,
                my_reputation       = excluded.my_reputation,
                is_squadron_faction = excluded.is_squadron_faction,
                data_timestamp      = excluded.data_timestamp,
                source              = excluded.source
            WHERE faction_snapshots.data_timestamp IS NULL
               OR excluded.data_timestamp >= faction_snapshots.data_timestamp
            """,
            (
                system_address,
                name,
                snapshot_date,
                float(influence) if isinstance(influence, (int, float)) else None,
                faction.get("Government"),
                faction.get("Allegiance"),
                faction.get("FactionState"),
                faction.get("Happiness_Localised") or faction.get("Happiness"),
                json.dumps(faction.get("ActiveStates")) if faction.get("ActiveStates") else None,
                json.dumps(faction.get("PendingStates")) if faction.get("PendingStates") else None,
                json.dumps(faction.get("RecoveringStates")) if faction.get("RecoveringStates") else None,
                1 if is_controlling else 0,
                float(my_reputation) if isinstance(my_reputation, (int, float)) else None,
                1 if is_squadron_faction else 0,
                normalized_timestamp,
                source,
            ),
        )
```

Do not change anything else in the method (the retention-cleanup `DELETE` statement immediately below stays exactly as-is).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_faction_snapshot_freshness.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add persistence/repository.py tests/test_faction_snapshot_freshness.py
git commit -m "feat: freshness-guarded upsert for faction_snapshots"
```

---

### Task 3: Wire all five write call sites

**Files:**
- Modify: `edc/core/edsm_faction_lookup.py`
- Modify: `edc/ui/panels/player_faction_panel.py`
- Modify: `edc/ui/main_window.py`
- Modify: `edc/core/eddn_market.py`

**Interfaces:**
- Consumes: `Repository.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, data_timestamp, source)` (Task 2) — every call site in this task must supply the two new arguments.

No automated test for this task — matches this codebase's existing convention (none of these five call sites, nor the files containing them, have any existing test coverage). Compile-check plus live verification.

- [ ] **Step 1: Capture EDSM's `lastUpdate` per faction**

In `edc/core/edsm_faction_lookup.py`, `_fetch_once()`'s per-faction dict construction currently reads (around line 229-240):

```python
        factions.append({
            "Name": name,
            "Influence": f.get("influence"),
            "Government": f.get("government"),
            "Allegiance": f.get("allegiance"),
            "FactionState": f.get("state"),
            "Happiness_Localised": f.get("happiness"),
            "ActiveStates": _states_to_journal_shape(f.get("activeStates")),
            "PendingStates": _states_to_journal_shape(f.get("pendingStates")),
            "RecoveringStates": _states_to_journal_shape(f.get("recoveringStates")),
            "is_controlling": bool(controlling_name and name == controlling_name),
        })
```

Add one new key, `"LastUpdate"`, holding EDSM's raw Unix epoch value as-is (normalization happens at the point of use in Task 2's helper, not here):

```python
        factions.append({
            "Name": name,
            "Influence": f.get("influence"),
            "Government": f.get("government"),
            "Allegiance": f.get("allegiance"),
            "FactionState": f.get("state"),
            "Happiness_Localised": f.get("happiness"),
            "ActiveStates": _states_to_journal_shape(f.get("activeStates")),
            "PendingStates": _states_to_journal_shape(f.get("pendingStates")),
            "RecoveringStates": _states_to_journal_shape(f.get("recoveringStates")),
            "is_controlling": bool(controlling_name and name == controlling_name),
            "LastUpdate": f.get("lastUpdate"),
        })
```

- [ ] **Step 2: Wire the three EDSM-backed call sites in `player_faction_panel.py`**

**Call site A** — bulk refresh worker (`_FactionRefreshWorker.run()`, around line 481):

Current:
```python
                for faction in result["factions"]:
                    is_controlling = bool(faction.pop("is_controlling", False))
                    repo.save_faction_snapshot(
                        result["system_address"], faction, snapshot_date, is_controlling
                    )
```

New:
```python
                for faction in result["factions"]:
                    is_controlling = bool(faction.pop("is_controlling", False))
                    data_timestamp = faction.pop("LastUpdate", None)
                    repo.save_faction_snapshot(
                        result["system_address"], faction, snapshot_date, is_controlling,
                        data_timestamp, "edsm",
                    )
```

**Call site B** — single-system manual add (around line 1455):

Current:
```python
            is_controlling = bool(match.pop("is_controlling", False))
            self._repo.save_faction_snapshot(
                result["system_address"], match, date.today().isoformat(), is_controlling,
            )
```

New:
```python
            is_controlling = bool(match.pop("is_controlling", False))
            data_timestamp = match.pop("LastUpdate", None)
            self._repo.save_faction_snapshot(
                result["system_address"], match, date.today().isoformat(), is_controlling,
                data_timestamp, "edsm",
            )
```

**Call site C** — CSV import (around line 380-403), which has TWO branches: an EDSM-matched branch and a fallback branch. Current:

```python
                if result:
                    match = next((f for f in result["factions"] if f.get("Name") == self._faction_name), None)
                    if match:
                        is_controlling = bool(match.pop("is_controlling", False))
                        faction_rec = match
                        snapshot_date = date.today().isoformat()
                        imported += 1
                    else:
                        # EDSM found the system but doesn't list our faction
                        # there (possibly stale on one side) — fall back to
                        # the CSV's own influence/government/allegiance so
                        # the row isn't dropped entirely.
                        faction_rec = {
                            "Name": self._faction_name,
                            "Influence": row.get("influence"),
                            "Government": row.get("government"),
                            "Allegiance": row.get("allegiance"),
                        }
                        is_controlling = False
                        snapshot_date = row.get("updated_date") or date.today().isoformat()
                        fallback_used += 1

                    repo.save_system_name_if_missing(result["system_address"], result["system_name"])
                    repo.save_faction_snapshot(result["system_address"], faction_rec, snapshot_date, is_controlling)
```

New — track `data_timestamp`/`source` per branch, pass both at the single shared call at the end:

```python
                if result:
                    match = next((f for f in result["factions"] if f.get("Name") == self._faction_name), None)
                    if match:
                        is_controlling = bool(match.pop("is_controlling", False))
                        data_timestamp = match.pop("LastUpdate", None)
                        source = "edsm"
                        faction_rec = match
                        snapshot_date = date.today().isoformat()
                        imported += 1
                    else:
                        # EDSM found the system but doesn't list our faction
                        # there (possibly stale on one side) — fall back to
                        # the CSV's own influence/government/allegiance so
                        # the row isn't dropped entirely.
                        faction_rec = {
                            "Name": self._faction_name,
                            "Influence": row.get("influence"),
                            "Government": row.get("government"),
                            "Allegiance": row.get("allegiance"),
                        }
                        is_controlling = False
                        snapshot_date = row.get("updated_date") or date.today().isoformat()
                        data_timestamp = row.get("updated_date")
                        source = "csv"
                        fallback_used += 1

                    repo.save_system_name_if_missing(result["system_address"], result["system_name"])
                    repo.save_faction_snapshot(
                        result["system_address"], faction_rec, snapshot_date, is_controlling,
                        data_timestamp, source,
                    )
```

- [ ] **Step 3: Wire the personal-journal-visit call site in `main_window.py`**

Current (`_save_faction_snapshots()`, around line 401-416):

```python
    def _save_faction_snapshots(self):
        system_address = getattr(self.state, "system_address", None)
        factions = getattr(self.state, "factions", None) or []
        if not isinstance(system_address, int) or not factions:
            return

        controlling = (getattr(self.state, "controlling_faction", None) or "").strip()
        today = date.today().isoformat()
        try:
            for f in factions:
                if not isinstance(f, dict):
                    continue
                is_controlling = bool(controlling) and f.get("Name") == controlling
                self.repo.save_faction_snapshot(system_address, f, today, is_controlling)
        except Exception:
            log.exception("Failed to save faction snapshots")
```

New — accepts the triggering event's timestamp as a parameter:

```python
    def _save_faction_snapshots(self, event_timestamp: str = ""):
        system_address = getattr(self.state, "system_address", None)
        factions = getattr(self.state, "factions", None) or []
        if not isinstance(system_address, int) or not factions:
            return

        controlling = (getattr(self.state, "controlling_faction", None) or "").strip()
        today = date.today().isoformat()
        try:
            for f in factions:
                if not isinstance(f, dict):
                    continue
                is_controlling = bool(controlling) and f.get("Name") == controlling
                self.repo.save_faction_snapshot(
                    system_address, f, today, is_controlling, event_timestamp, "journal",
                )
        except Exception:
            log.exception("Failed to save faction snapshots")
```

Update the one call site (around line 1917):

Current:
```python
        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots()
```

New:
```python
        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots(evt.get("timestamp") or "")
```

- [ ] **Step 4: Wire the EDDN listener flush path in `eddn_market.py`**

Current (`write_buffers()`, around line 151-158):

```python
    if factions:
        for system_address, (system_name, faction, is_controlling, timestamp) in factions:
            try:
                repo.save_system_name_if_missing(system_address, system_name)
                snapshot_date = (timestamp or "")[:10] or date.today().isoformat()
                repo.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling)
            except Exception:
                log.exception("Failed to flush faction sighting for system_address=%s", system_address)
```

New:
```python
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
```

- [ ] **Step 5: Compile-check everything touched**

Run: `python -m py_compile edc/core/edsm_faction_lookup.py edc/ui/panels/player_faction_panel.py edc/ui/main_window.py edc/core/eddn_market.py`
Expected: no output (success)

- [ ] **Step 6: Run the full test suite to confirm nothing broke**

Run: `python -m pytest -v`
Expected: PASS (all tests, including the 11 new ones from Task 2)

- [ ] **Step 7: Live verification**

Per this project's established convention (`CLAUDE.md`: confirmation means working in-game or visually confirmed in the running app):

1. Launch the app, let a normal play session run (personal visits) and/or let the daily EDSM refresh or a manual "Refresh All" run.
2. After some real writes have happened, spot-check `faction_snapshots` directly (e.g. via a quick `sqlite3`/Python query, same approach used to diagnose the original discrepancy this session) — confirm `data_timestamp` and `source` are populated (not `NULL`/empty) on freshly-written rows, and that `source` values are only ever `"journal"`, `"edsm"`, `"eddn"`, or `"csv"`.
3. If practical, confirm the guard itself: find or wait for a case where two different pipelines write the same system+faction+day, and confirm the row's `data_timestamp` after both writes matches whichever was actually more recent, not just whichever wrote last.

- [ ] **Step 8: Commit**

```bash
git add edc/core/edsm_faction_lookup.py edc/ui/panels/player_faction_panel.py edc/ui/main_window.py edc/core/eddn_market.py
git commit -m "feat: wire real data timestamps and source tags into all faction_snapshots writers"
```
