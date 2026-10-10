# BGS Tasks Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A manually-entered list of squadron BGS tasks (Boost / Vote / Fight / PowerPlay / Note) with live per-task progress in a dialog and a one-line hint on the Overview HUD.

**Architecture:** Tasks live in a new personal-DB table `bgs_tasks`. A pure-logic module `edc/core/bgs_tasks.py` turns each task plus data the app already stores (session activity report, `net.system_bgs_status`, `faction_snapshots`, `systems.pp_*`) into a "view" dict (status, lines, warnings, HUD text). A new `BgsTasksDialog` (opened from the Player Faction panel) renders views; `MainWindow` pushes refreshes and sets the Overview HUD hint. Elections start being stored in `net.system_bgs_status` so Vote tasks have a days-won score.

**Tech Stack:** Python 3.12, PyQt6, SQLite (personal `main` DB + attached `net` cache DB), pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md`

## Global Constraints

- Run tests with `.venv/Scripts/python.exe -m pytest` from the repo root `C:\Dev\EDChronicle` (never system Python).
- Known pre-existing failures, unrelated, leave alone: `tests/test_coords_backfill.py::test_finds_tracked_system_with_no_coords_row`, `tests/test_coords_backfill.py::test_respects_limit`, `tests/test_interstellar_factors.py::test_excludes_station_in_system_where_faction_has_non_controlling_presence`.
- SQLite connections are never shared across threads. This feature adds no threads.
- Never push data to any third-party platform.
- UI labels use full words, never cryptic abbreviations (no ".INF", "wt", "pri/sec").
- Boost limits are labelled as squadron guidance, not Frontier numbers. Defaults: tier score 25, bounties 20,000,000 CR, exploration 20,000,000 CR; trade profit has no limit.
- Timestamps written by this feature use `"%Y-%m-%dT%H:%M:%SZ"` (UTC), matching `_normalize_data_timestamp` in `persistence/repository.py`, so string comparison sorts chronologically.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Personal DB schema changes go in `persistence/database.py` `run_migrations()` → `personal_migrations` list (append at the end; never edit existing entries).

## File Structure

| File | Responsibility |
|---|---|
| `persistence/repository.py` (modify) | Store elections; clear ended conflicts on a newer own-journal reading; `bgs_tasks` CRUD, system/faction name lookup |
| `edc/core/eddn_listener.py` (modify) | Keep elections from EDDN messages |
| `edc/ui/panels/combat_bgs_status_panel.py` (modify) | Keep Combat System Status war-only (ignore elections) |
| `persistence/database.py` (modify) | `bgs_tasks` table migration |
| `edc/config.py` (modify) | Three Boost-limit settings |
| `edc/core/bgs_tasks.py` (create) | Pure logic: activity aggregation, conflict lookup, per-task view/status, HUD line, input validation |
| `edc/ui/panels/bgs_tasks_dialog.py` (create) | The BGS Tasks window |
| `edc/ui/panels/player_faction_panel.py` (modify) | "BGS Tasks…" button, dialog ownership, refresh push, `bgs_tasks_changed` signal |
| `edc/ui/panels/overview_panel.py` (modify) | HUD hint label |
| `edc/ui/main_window.py` (modify) | Settings spinboxes, limit getter, refresh wiring, HUD hint |

---

### Task 1: Store elections and clear ended conflicts

**Files:**
- Modify: `persistence/repository.py` (`save_system_bgs_status`, around lines 606-670)
- Modify: `edc/core/eddn_listener.py:56-70` (`_extract_bgs_status`)
- Modify: `edc/ui/panels/combat_bgs_status_panel.py:76-115` (`_merge_results`, `_conflicts_text`)
- Modify: `docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md` (one-line clarification)
- Test: `tests/test_bgs_status_repository.py`, `tests/test_eddn_bgs_status_parsing.py`, `tests/test_combat_bgs_status_panel_helpers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `net.system_bgs_status.conflicts` JSON entries may now have `"war_type": "election"` (same keys as war entries: `faction1, faction2, war_type, status, won_days1, won_days2, stake1, stake2`). A journal-sourced save with no relevant conflicts/states now rewrites an existing row's `conflicts`/`faction_states` to `[]`. `Repository.get_bgs_status_for_system(address)` is unchanged in signature and now returns elections too.

- [ ] **Step 1: Write the failing repository tests**

In `tests/test_bgs_status_repository.py`, replace the whole body of `test_save_stores_war_conflict_and_ignores_non_war_conflicts` (keep its position) with this renamed test:

```python
def test_save_stores_war_and_election_conflicts_and_ignores_others(repo):
    conflicts = [
        {"WarType": "election", "Status": "", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}},
        {"WarType": "war", "Status": "active", "Faction1": {"Name": "C", "WonDays": 2}, "Faction2": {"Name": "D", "WonDays": 1}},
        {"WarType": "", "Status": "", "Faction1": {"Name": "E"}, "Faction2": {"Name": "F"}},
    ]
    repo.save_system_bgs_status(1, "Sol", conflicts=conflicts, factions=[],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is not None
    stored = json.loads(row["conflicts"])
    assert [c["war_type"] for c in stored] == ["election", "war"]
    assert stored[1] == {"faction1": "C", "faction2": "D", "war_type": "war", "status": "active",
                         "won_days1": 2, "won_days2": 1, "stake1": None, "stake2": None}
```

Append these tests at the end of the same file:

```python
# --- ended conflicts are cleared by a newer own-journal reading ---

_WAR = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}}]


def _stored_conflicts(repo):
    row = repo.db.conn.execute("SELECT conflicts FROM system_bgs_status WHERE system_address = 1").fetchone()
    return json.loads(row["conflicts"])


def test_newer_journal_reading_with_nothing_relevant_clears_ended_conflict(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-20T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-21T00:00:00Z", "journal")
    assert _stored_conflicts(repo) == []


def test_older_journal_reading_does_not_clear_newer_conflict(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-21T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-20T00:00:00Z", "journal")
    assert len(_stored_conflicts(repo)) == 1


def test_eddn_and_edsm_readings_never_clear(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-20T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-21T00:00:00Z", "eddn")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-22T00:00:00Z", "edsm")
    assert len(_stored_conflicts(repo)) == 1
```

- [ ] **Step 2: Write the failing EDDN parsing and Combat panel tests**

In `tests/test_eddn_bgs_status_parsing.py`, in `test_extract_bgs_status_returns_war_conflicts_and_multistate_factions`, replace the line

```python
    assert len(conflicts) == 1 and conflicts[0]["WarType"] == "war"
```

with

```python
    assert [c["WarType"] for c in conflicts] == ["war", "election"]
```

Append to `tests/test_combat_bgs_status_panel_helpers.py`:

```python
# --- elections are stored for the BGS Tasks tracker but never shown here ---

def test_conflicts_text_skips_elections():
    conflicts = [
        {"war_type": "election", "faction1": "A", "won_days1": 1, "faction2": "B", "won_days2": 0},
        {"war_type": "war", "faction1": "C", "won_days1": 2, "faction2": "D", "won_days2": 1},
    ]
    assert _conflicts_text(conflicts) == "War: C (2) vs D (1)"


def test_conflicts_text_election_only_is_empty():
    conflicts = [{"war_type": "election", "faction1": "A", "won_days1": 1, "faction2": "B", "won_days2": 0}]
    assert _conflicts_text(conflicts) == ""


def test_merge_results_drops_election_only_rows_and_strips_elections():
    election = {"war_type": "election", "faction1": "A", "won_days1": 1, "faction2": "B", "won_days2": 0}
    war = {"war_type": "war", "faction1": "C", "won_days1": 2, "faction2": "D", "won_days2": 1}
    bgs = [
        {"system_name": "OnlyElection", "distance_ly": 1.0, "conflicts": [election],
         "faction_states": [], "data_timestamp": "2026-09-26T00:00:00Z"},
        {"system_name": "Both", "distance_ly": 2.0, "conflicts": [election, war],
         "faction_states": [], "data_timestamp": "2026-09-26T00:00:00Z"},
    ]
    merged = _merge_results(bgs, [])
    assert [r["system_name"] for r in merged] == ["Both"]
    assert merged[0]["conflicts"] == [war]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_status_repository.py tests/test_eddn_bgs_status_parsing.py tests/test_combat_bgs_status_panel_helpers.py -q -p no:cacheprovider`
Expected: FAIL — `test_save_stores_war_and_election_conflicts_and_ignores_others`, `test_newer_journal_reading_with_nothing_relevant_clears_ended_conflict`, `test_extract_bgs_status_returns_war_conflicts_and_multistate_factions`, `test_conflicts_text_skips_elections`, `test_merge_results_drops_election_only_rows_and_strips_elections` fail (the others may already pass).

- [ ] **Step 4: Implement — repository**

In `persistence/repository.py`, `save_system_bgs_status`: change the docstring's first sentence from `Upserts current War/CivilWar conflicts` to `Upserts current War/CivilWar/Election conflicts`, and change

```python
            if war_type not in ("war", "civilwar"):
                continue
```

to

```python
            if war_type not in ("war", "civilwar", "election"):
                continue
```

Then replace

```python
        if not war_conflicts and not multistate_factions:
            return

        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
```

with

```python
        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        if not war_conflicts and not multistate_factions:
            # The player's own journal always carries the full Conflicts/
            # Factions picture, so a newer own reading with nothing relevant
            # means a stored war/election has ended -- clear it rather than
            # leave it looking current. EDDN listener messages with nothing
            # relevant are never emitted, and EDSM has no Conflicts data at
            # all, so neither may clear. UPDATE only: never creates a row, and
            # rows holding only system-profile columns (conflicts NULL) are
            # left alone.
            if source == "journal":
                self.db.execute(
                    """
                    UPDATE net.system_bgs_status
                    SET conflicts = '[]', faction_states = '[]', data_timestamp = ?, source = ?
                    WHERE system_address = ? AND conflicts IS NOT NULL
                      AND (data_timestamp IS NULL OR ? >= data_timestamp)
                    """,
                    (normalized_timestamp, source, system_address, normalized_timestamp),
                )
            return
```

(The existing `normalized_timestamp = _normalize_data_timestamp(data_timestamp)` line that followed the old early return must now appear only once, above the `if`.)

- [ ] **Step 5: Implement — EDDN listener**

In `edc/core/eddn_listener.py`, `_extract_bgs_status`: change the docstring's first words `War/CivilWar conflicts` to `War/CivilWar/Election conflicts`, and change

```python
        if isinstance(c, dict) and str(c.get("WarType", "")).lower() in ("war", "civilwar")
```

to

```python
        if isinstance(c, dict) and str(c.get("WarType", "")).lower() in ("war", "civilwar", "election")
```

- [ ] **Step 6: Implement — Combat System Status panel**

In `edc/ui/panels/combat_bgs_status_panel.py`, add this function directly above `def _merge_results`:

```python
def _combat_conflicts(conflicts: List[dict]) -> List[dict]:
    """Elections are stored alongside wars (for the BGS Tasks tracker) but
    are not combat -- this panel only ever shows War/Civil War."""
    return [c for c in (conflicts or []) if c.get("war_type") != "election"]
```

In `_merge_results`, replace

```python
    for r in bgs_results:
        merged[r["system_name"]] = {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": r["conflicts"], "faction_states": r["faction_states"],
            "tiers": [], "data_timestamp": r["data_timestamp"],
        }
```

with

```python
    for r in bgs_results:
        conflicts = _combat_conflicts(r["conflicts"])
        if not conflicts and not r["faction_states"]:
            continue
        merged[r["system_name"]] = {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": conflicts, "faction_states": r["faction_states"],
            "tiers": [], "data_timestamp": r["data_timestamp"],
        }
```

In `_conflicts_text`, replace

```python
    if not conflicts:
        return ""
    parts = []
    for c in conflicts:
```

with

```python
    conflicts = _combat_conflicts(conflicts)
    if not conflicts:
        return ""
    parts = []
    for c in conflicts:
```

- [ ] **Step 7: Clarify the spec's "Conflict ended" rule**

In `docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md`, replace

```
- **Conflict ended** — Vote/Fight: the conflict is no longer reported for
  the system. The task stays until removed.
```

with

```
- **Conflict ended** — Vote/Fight: the system has been read since the task
  was created and the conflict is no longer in it. Ended conflicts are
  cleared by the player's own journal visit (EDDN/EDSM readings never
  clear, since they don't reliably carry the full picture). The task stays
  until removed.
```

In the same spec file, in the Task types table's PowerPlay row, replace

```
`systems.pp_*` via `get_system_powerplay_snapshot()`; FDev CSV cache as fallback
```

with

```
`systems.pp_*` via `get_system_powerplay_snapshot()` (your own last visit; no CSV fallback in v1)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_status_repository.py tests/test_eddn_bgs_status_parsing.py tests/test_combat_bgs_status_panel_helpers.py -q -p no:cacheprovider`
Expected: PASS (all).

Run the full suite: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`
Expected: only the 3 known pre-existing failures.

- [ ] **Step 9: Commit**

```bash
git add persistence/repository.py edc/core/eddn_listener.py edc/ui/panels/combat_bgs_status_panel.py docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md tests/test_bgs_status_repository.py tests/test_eddn_bgs_status_parsing.py tests/test_combat_bgs_status_panel_helpers.py
git commit -m "feat: store elections and clear ended conflicts in system BGS status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `bgs_tasks` table and repository methods

**Files:**
- Modify: `persistence/database.py` (`run_migrations()` → end of `personal_migrations` list, currently ending with the `faction_bounties` table and its index)
- Modify: `persistence/repository.py` (add methods; place them directly after `get_session_activity_report`)
- Test: `tests/test_bgs_tasks_repository.py` (create)

**Interfaces:**
- Consumes: `systems (system_address, system_name)`, `net.system_bgs_status (system_address, system_name)`, `faction_snapshots (system_address, faction_name)`.
- Produces (all on `Repository`):
  - `resolve_system(name: str) -> Optional[tuple[int, str]]` — `(system_address, canonical_name)`, case-insensitive, or `None`.
  - `add_bgs_task(system_name: str, task_type: str, faction_name: Optional[str] = None, opponent_name: Optional[str] = None, note: Optional[str] = None) -> int` — returns the new id.
  - `list_bgs_tasks() -> list[dict]` — keys `id, system_address, system_name, task_type, faction_name, opponent_name, note, sort_order, created_at`; ordered by `sort_order, id`; resolves unresolved names as a side effect.
  - `delete_bgs_task(task_id: int) -> None`
  - `move_bgs_task(task_id: int, direction: int) -> None` — `-1` up, `+1` down.
  - `get_known_system_names() -> list[str]`
  - `get_known_faction_names(system_address: int) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bgs_tasks_repository.py`:

```python
"""bgs_tasks table + Repository CRUD for the BGS Tasks tracker. Real
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
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (?, ?)", (system_address, system_name))


def test_resolve_system_is_case_insensitive_and_returns_canonical_name(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    assert repo.resolve_system("ekono") == (12345, "Ekono")
    assert repo.resolve_system("  EKONO ") == (12345, "Ekono")


def test_resolve_system_falls_back_to_eddn_bgs_status(tmp_path):
    repo = _repo(tmp_path)
    repo.db.execute(
        "INSERT INTO net.system_bgs_status (system_address, system_name, conflicts, faction_states, data_timestamp, source) "
        "VALUES (777, 'Kanuket', '[]', '[]', '2026-09-26T00:00:00Z', 'eddn')"
    )
    assert repo.resolve_system("kanuket") == (777, "Kanuket")


def test_resolve_system_unknown_or_blank_is_none(tmp_path):
    repo = _repo(tmp_path)
    assert repo.resolve_system("Nowhere") is None
    assert repo.resolve_system("") is None


def test_add_and_list_tasks_in_entry_order(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    first = repo.add_bgs_task("ekono", "boost", faction_name="Elite United Worlds")
    second = repo.add_bgs_task("Kanuket", "vote", faction_name="Remnants of the Code", opponent_name="Elite United Worlds")
    tasks = repo.list_bgs_tasks()
    assert [t["id"] for t in tasks] == [first, second]
    assert tasks[0]["system_address"] == 12345
    assert tasks[0]["system_name"] == "Ekono"
    assert tasks[0]["task_type"] == "boost"
    assert tasks[0]["opponent_name"] is None
    assert tasks[1]["system_address"] is None  # not seen yet
    assert tasks[1]["system_name"] == "Kanuket"
    assert tasks[1]["opponent_name"] == "Elite United Worlds"
    assert len(tasks[0]["created_at"]) == 20 and tasks[0]["created_at"].endswith("Z")


def test_list_resolves_a_system_seen_after_the_task_was_added(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("kanuket", "vote", faction_name="A", opponent_name="B")
    _seed_system(repo, 777, "Kanuket")
    tasks = repo.list_bgs_tasks()
    assert tasks[0]["system_address"] == 777
    assert tasks[0]["system_name"] == "Kanuket"
    row = repo.db.conn.execute("SELECT system_address FROM bgs_tasks").fetchone()
    assert row["system_address"] == 777  # persisted, not just returned


def test_delete_task(tmp_path):
    repo = _repo(tmp_path)
    task_id = repo.add_bgs_task("Ekono", "note", note="check in")
    repo.delete_bgs_task(task_id)
    assert repo.list_bgs_tasks() == []


def test_move_task_up_and_down(tmp_path):
    repo = _repo(tmp_path)
    a = repo.add_bgs_task("A", "note", note="a")
    b = repo.add_bgs_task("B", "note", note="b")
    c = repo.add_bgs_task("C", "note", note="c")
    repo.move_bgs_task(c, -1)
    assert [t["id"] for t in repo.list_bgs_tasks()] == [a, c, b]
    repo.move_bgs_task(a, +1)
    assert [t["id"] for t in repo.list_bgs_tasks()] == [c, a, b]
    repo.move_bgs_task(c, -1)  # already first -- no-op
    assert [t["id"] for t in repo.list_bgs_tasks()] == [c, a, b]


def test_known_names(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 2, "Kanuket")
    _seed_system(repo, 1, "Ekono")
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Hungarian Wolves', '2026-09-25')"
    )
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Elite United Worlds', '2026-09-25')"
    )
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Elite United Worlds', '2026-09-26')"
    )
    assert repo.get_known_system_names() == ["Ekono", "Kanuket"]
    assert repo.get_known_faction_names(1) == ["Elite United Worlds", "Hungarian Wolves"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_repository.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'resolve_system'` (and similar).

- [ ] **Step 3: Add the migration**

In `persistence/database.py`, append to the end of the `personal_migrations` list (after the `idx_faction_bounties_lookup` index entry):

```python
            """CREATE TABLE IF NOT EXISTS bgs_tasks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                system_address INTEGER,
                system_name    TEXT    NOT NULL,
                task_type      TEXT    NOT NULL,
                faction_name   TEXT,
                opponent_name  TEXT,
                note           TEXT,
                sort_order     INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT    NOT NULL
            )""",
```

- [ ] **Step 4: Add the repository methods**

In `persistence/repository.py`, directly after the end of `get_session_activity_report` (after its `return report`), add:

```python
    # --- BGS Tasks tracker (docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md) ---

    def resolve_system(self, name: str) -> Optional[tuple]:
        """(system_address, canonical_name) for a system name typed by the
        user, case-insensitive -- the personal systems table first, then
        EDDN's net.system_bgs_status. None if the name was never seen."""
        name = (name or "").strip()
        if not name:
            return None
        for sql in (
            "SELECT system_address, system_name FROM systems WHERE system_name = ? COLLATE NOCASE LIMIT 1",
            "SELECT system_address, system_name FROM net.system_bgs_status WHERE system_name = ? COLLATE NOCASE LIMIT 1",
        ):
            row = self.db.conn.execute(sql, (name,)).fetchone()
            if row and row["system_address"] is not None:
                return row["system_address"], row["system_name"] or name
        return None

    def add_bgs_task(
        self, system_name: str, task_type: str, faction_name: Optional[str] = None,
        opponent_name: Optional[str] = None, note: Optional[str] = None,
    ) -> int:
        from datetime import datetime, timezone

        resolved = self.resolve_system(system_name)
        address, name = resolved if resolved else (None, (system_name or "").strip())
        next_order = self.db.conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bgs_tasks").fetchone()[0]
        cur = self.db.execute(
            "INSERT INTO bgs_tasks (system_address, system_name, task_type, faction_name, opponent_name, "
            "note, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                address, name, task_type, faction_name or None, opponent_name or None, note or None,
                next_order, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        return cur.lastrowid

    def list_bgs_tasks(self) -> list[dict]:
        """All tasks in the user's priority order. A task whose system name
        wasn't known when it was added is resolved here the first time that
        system shows up (own visit or EDDN), and the resolution is saved."""
        rows = [dict(r) for r in self.db.conn.execute(
            "SELECT id, system_address, system_name, task_type, faction_name, opponent_name, note, "
            "sort_order, created_at FROM bgs_tasks ORDER BY sort_order, id"
        ).fetchall()]
        for r in rows:
            if r["system_address"] is None and r["system_name"]:
                resolved = self.resolve_system(r["system_name"])
                if resolved:
                    r["system_address"], r["system_name"] = resolved
                    self.db.execute(
                        "UPDATE bgs_tasks SET system_address = ?, system_name = ? WHERE id = ?",
                        (resolved[0], resolved[1], r["id"]),
                    )
        return rows

    def delete_bgs_task(self, task_id: int) -> None:
        self.db.execute("DELETE FROM bgs_tasks WHERE id = ?", (task_id,))

    def move_bgs_task(self, task_id: int, direction: int) -> None:
        """direction -1 moves the task up one place, +1 down one place."""
        ids = [r["id"] for r in self.db.conn.execute("SELECT id FROM bgs_tasks ORDER BY sort_order, id").fetchall()]
        if task_id not in ids:
            return
        i = ids.index(task_id)
        j = i + direction
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        with self.db.deferred_commit():
            for order, tid in enumerate(ids):
                self.db.execute("UPDATE bgs_tasks SET sort_order = ? WHERE id = ?", (order, tid))

    def get_known_system_names(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT system_name FROM systems WHERE system_name IS NOT NULL AND system_name != '' ORDER BY system_name"
        ).fetchall()
        return [r["system_name"] for r in rows]

    def get_known_faction_names(self, system_address: int) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT faction_name FROM faction_snapshots WHERE system_address = ? ORDER BY faction_name",
            (system_address,),
        ).fetchall()
        return [r["faction_name"] for r in rows]
```

(`Optional` is already imported at the top of `repository.py`; confirm with a search before adding an import.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_repository.py -q -p no:cacheprovider`
Expected: PASS.

Full suite: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider` — only the 3 known failures.

- [ ] **Step 6: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_bgs_tasks_repository.py
git commit -m "feat: bgs_tasks table and repository methods for the BGS tasks tracker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Boost-limit settings

**Files:**
- Modify: `edc/config.py` (`AppConfig`, `ConfigStore.load`, `ConfigStore.save`)
- Modify: `edc/ui/main_window.py` (Settings tab after the "Market search radius" row, around line 2637; handlers after `_on_market_radius_changed`, around line 4421)
- Test: `tests/test_config_bgs_limits.py` (create)

**Interfaces:**
- Produces: `AppConfig.bgs_limit_tier_score: int = 25`, `AppConfig.bgs_limit_bounties_cr: int = 20_000_000`, `AppConfig.bgs_limit_exploration_cr: int = 20_000_000`; `MainWindow._on_bgs_limit_tier_changed(value: int)`, `_on_bgs_limit_bounties_changed(value_millions: int)`, `_on_bgs_limit_exploration_changed(value_millions: int)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_bgs_limits.py`:

```python
"""Squadron Boost limits for the BGS Tasks tracker -- stored in
settings.json like every other setting, defaults from the squadron guide."""
import json
from types import SimpleNamespace

from edc.config import AppConfig, ConfigStore
from edc.ui.main_window import MainWindow


def test_defaults():
    cfg = AppConfig()
    assert cfg.bgs_limit_tier_score == 25
    assert cfg.bgs_limit_bounties_cr == 20_000_000
    assert cfg.bgs_limit_exploration_cr == 20_000_000


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = AppConfig()
    cfg.bgs_limit_tier_score = 30
    cfg.bgs_limit_bounties_cr = 15_000_000
    cfg.bgs_limit_exploration_cr = 25_000_000
    store.save(cfg)
    loaded = store.load()
    assert loaded.bgs_limit_tier_score == 30
    assert loaded.bgs_limit_bounties_cr == 15_000_000
    assert loaded.bgs_limit_exploration_cr == 25_000_000


def test_missing_keys_in_an_older_settings_file_use_defaults(tmp_path):
    store = ConfigStore(tmp_path)
    store.ensure_dirs()
    store.path.write_text(json.dumps({"schema_version": 2, "journal_dir": None}), encoding="utf-8")
    loaded = store.load()
    assert loaded.bgs_limit_tier_score == 25
    assert loaded.bgs_limit_bounties_cr == 20_000_000


def _fake_self():
    saved = []
    return SimpleNamespace(cfg=AppConfig(), cfg_store=SimpleNamespace(save=saved.append), _saved=saved)


def test_settings_handlers_store_values_and_save():
    fake_self = _fake_self()
    MainWindow._on_bgs_limit_tier_changed(fake_self, 40)
    MainWindow._on_bgs_limit_bounties_changed(fake_self, 12)
    MainWindow._on_bgs_limit_exploration_changed(fake_self, 30)
    assert fake_self.cfg.bgs_limit_tier_score == 40
    assert fake_self.cfg.bgs_limit_bounties_cr == 12_000_000
    assert fake_self.cfg.bgs_limit_exploration_cr == 30_000_000
    assert len(fake_self._saved) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_bgs_limits.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: 'AppConfig' object has no attribute 'bgs_limit_tier_score'`.

- [ ] **Step 3: Implement config**

In `edc/config.py`, `AppConfig`, add after `search_indexes_ensured: bool = False`:

```python
    # BGS Tasks tracker Boost limits per tick -- squadron guidance, not
    # Frontier numbers (Frontier publishes none).
    bgs_limit_tier_score: int = 25
    bgs_limit_bounties_cr: int = 20_000_000
    bgs_limit_exploration_cr: int = 20_000_000
```

In `ConfigStore.load`, inside the `AppConfig(...)` constructor call, add after the `search_indexes_ensured=...` line:

```python
                bgs_limit_tier_score=int(data.get("bgs_limit_tier_score", 25) or 25),
                bgs_limit_bounties_cr=int(data.get("bgs_limit_bounties_cr", 20_000_000) or 20_000_000),
                bgs_limit_exploration_cr=int(data.get("bgs_limit_exploration_cr", 20_000_000) or 20_000_000),
```

In `ConfigStore.save`, inside the dict, add after the `"search_indexes_ensured": ...` line:

```python
                        "bgs_limit_tier_score": int(getattr(cfg, "bgs_limit_tier_score", 25) or 25),
                        "bgs_limit_bounties_cr": int(getattr(cfg, "bgs_limit_bounties_cr", 20_000_000) or 20_000_000),
                        "bgs_limit_exploration_cr": int(getattr(cfg, "bgs_limit_exploration_cr", 20_000_000) or 20_000_000),
```

- [ ] **Step 4: Implement Settings UI and handlers**

In `edc/ui/main_window.py`, directly after `st.addLayout(market_row)` (end of the "Market search radius" block), add:

```python
        # --- Squadron BGS limits (BGS Tasks tracker) ---
        bgs_row = QHBoxLayout()
        bgs_row.addWidget(QLabel("Squadron BGS limits per tick — missions tier score:"))
        self.bgs_limit_tier_spin = QSpinBox()
        self.bgs_limit_tier_spin.setRange(1, 500)
        self.bgs_limit_tier_spin.setValue(int(getattr(self.cfg, "bgs_limit_tier_score", 25) or 25))
        self.bgs_limit_tier_spin.valueChanged.connect(self._on_bgs_limit_tier_changed)
        bgs_row.addWidget(self.bgs_limit_tier_spin)
        bgs_row.addWidget(QLabel("bounties:"))
        self.bgs_limit_bounties_spin = QSpinBox()
        self.bgs_limit_bounties_spin.setRange(1, 2000)
        self.bgs_limit_bounties_spin.setSuffix(" M CR")
        self.bgs_limit_bounties_spin.setValue(int(getattr(self.cfg, "bgs_limit_bounties_cr", 20_000_000) or 20_000_000) // 1_000_000)
        self.bgs_limit_bounties_spin.valueChanged.connect(self._on_bgs_limit_bounties_changed)
        bgs_row.addWidget(self.bgs_limit_bounties_spin)
        bgs_row.addWidget(QLabel("exploration:"))
        self.bgs_limit_exploration_spin = QSpinBox()
        self.bgs_limit_exploration_spin.setRange(1, 2000)
        self.bgs_limit_exploration_spin.setSuffix(" M CR")
        self.bgs_limit_exploration_spin.setValue(int(getattr(self.cfg, "bgs_limit_exploration_cr", 20_000_000) or 20_000_000) // 1_000_000)
        self.bgs_limit_exploration_spin.valueChanged.connect(self._on_bgs_limit_exploration_changed)
        bgs_row.addWidget(self.bgs_limit_exploration_spin)
        bgs_row.addStretch(1)
        bgs_row_widget_note = QLabel("Squadron guidance, not Frontier numbers — used by the BGS Tasks tracker.")
        bgs_row_widget_note.setStyleSheet("color:#888888; font-size:11px;")
        st.addLayout(bgs_row)
        st.addWidget(bgs_row_widget_note)
```

Directly after the `_on_market_radius_changed` method, add:

```python
    def _on_bgs_limit_tier_changed(self, value: int):
        self.cfg.bgs_limit_tier_score = int(value)
        self.cfg_store.save(self.cfg)

    def _on_bgs_limit_bounties_changed(self, value_millions: int):
        self.cfg.bgs_limit_bounties_cr = int(value_millions) * 1_000_000
        self.cfg_store.save(self.cfg)

    def _on_bgs_limit_exploration_changed(self, value_millions: int):
        self.cfg.bgs_limit_exploration_cr = int(value_millions) * 1_000_000
        self.cfg_store.save(self.cfg)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_bgs_limits.py -q -p no:cacheprovider`
Expected: PASS. Full suite: only the 3 known failures.

- [ ] **Step 6: Commit**

```bash
git add edc/config.py edc/ui/main_window.py tests/test_config_bgs_limits.py
git commit -m "feat: editable squadron Boost limits for the BGS tasks tracker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Core task logic (`edc/core/bgs_tasks.py`)

**Files:**
- Create: `edc/core/bgs_tasks.py`
- Test: `tests/test_bgs_tasks_core.py` (create)

**Interfaces:**
- Consumes: Task 2's `Repository.list_bgs_tasks()` dict shape; `Repository.get_session_activity_report(since)` shape `{date: {system_name: {faction_name: {"missions": {"count", "weighted", ...}, "combat_bonds_total", "bounties_total", "cz_kills": {6 keys}, "trade_sold": {"commodity", "exploration", "exobiology"}}}}}` (`commodity` is trade profit); `Repository.get_bgs_status_for_system(addr)` → `{"conflicts": [...], "faction_states": [...], "data_timestamp": str}` or `None`; `Repository.get_faction_history(addr)` → list of dicts with `faction_name`, `snapshot_date`, `influence` (0-1 fraction), newest first; `Repository.get_system_powerplay_snapshot(addr)` → dict with `pp_state`, `pp_control_progress` (0-1 fraction), `pp_controlling_power`, `pp_data_timestamp`, or `None`.
- Produces:
  - Constants `TASK_TYPES`, `TASK_LABELS`, `STATUS_DONE`, `STATUS_TODO`, `STATUS_LOSING`, `STATUS_ENDED`, `STATUS_NO_DATA`, `STATUS_TRACKING`, `STATUS_COLORS`, `DEFAULT_LIMITS`.
  - `bgs_limits(cfg) -> dict` (keys `tier_score`, `bounties`, `exploration`)
  - `validate_task_input(system: str, task_type: str, faction: str, opponent: str, note: str) -> str` ("" when valid)
  - `task_title(task: dict) -> str`
  - `faction_activity(report: dict, system_name: str, faction_name: str) -> dict`
  - `find_conflict(bgs_status: Optional[dict], faction_name: str, opponent_name: str, war_types: tuple) -> Optional[dict]`
  - `build_task_view(task, report, bgs_status, history, pp, limits) -> dict` with keys `task, status, lines (list[str]), warnings (list[str]), hud (str), updated_at (Optional[str])`
  - `build_task_views(repo, since: str, limits: dict, system_address: Optional[int] = None) -> list[dict]`
  - `hud_line(views: list[dict]) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bgs_tasks_core.py`:

```python
"""edc/core/bgs_tasks.py -- per-task progress/status for the BGS Tasks
tracker, from data the app already stores. Pure functions; fake inputs in
the exact shapes the Repository returns."""
from types import SimpleNamespace

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, STATUS_DONE, STATUS_ENDED, STATUS_LOSING, STATUS_NO_DATA, STATUS_TODO, STATUS_TRACKING,
    bgs_limits, build_task_view, build_task_views, faction_activity, find_conflict, hud_line,
    task_title, validate_task_input,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None, opponent=None, note=None, system="Ekono", address=12345,
          created_at="2026-09-26T00:00:00Z", task_id=1):
    return {"id": task_id, "system_address": address, "system_name": system, "task_type": task_type,
            "faction_name": faction, "opponent_name": opponent, "note": note, "sort_order": 0,
            "created_at": created_at}


def _entry(count=0, weighted=0, bonds=0, bounties=0, cz_space_h=0, profit=0, exploration=0, exobiology=0):
    return {
        "missions": {"count": count, "weighted": weighted, "primary_count": count, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": bonds, "bounties_total": bounties,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": cz_space_h},
        "trade_sold": {"commodity": profit, "exploration": exploration, "exobiology": exobiology},
    }


def _conflict(war_type, f1, d1, f2, d2, status="active"):
    return {"faction1": f1, "faction2": f2, "war_type": war_type, "status": status,
            "won_days1": d1, "won_days2": d2, "stake1": None, "stake2": None}


# --- small helpers ---

def test_bgs_limits_reads_cfg():
    cfg = SimpleNamespace(bgs_limit_tier_score=30, bgs_limit_bounties_cr=10_000_000, bgs_limit_exploration_cr=5_000_000)
    assert bgs_limits(cfg) == {"tier_score": 30, "bounties": 10_000_000, "exploration": 5_000_000}


def test_validate_task_input():
    assert validate_task_input("Ekono", "boost", "EUW", "", "") == ""
    assert validate_task_input("", "boost", "EUW", "", "") == "Enter a system name."
    assert validate_task_input("Ekono", "boost", "", "", "") == "Enter the faction to support."
    assert validate_task_input("Ekono", "vote", "A", "", "") == "Enter the opposing faction."
    assert validate_task_input("Ekono", "fight", "A", "B", "") == ""
    assert validate_task_input("", "note", "", "", "") == "Enter the note text."
    assert validate_task_input("", "note", "", "", "watch Andel") == ""
    assert validate_task_input("Ekono", "powerplay", "", "", "") == ""


def test_task_title():
    assert task_title(_task("boost", "Elite United Worlds")) == "Ekono — Boost Elite United Worlds"
    assert task_title(_task("vote", "A", "B", system="Kanuket")) == "Kanuket — Vote A vs B"
    assert task_title(_task("note", note="x", system="")) == "Note"


def test_faction_activity_sums_across_days_case_insensitively():
    report = {
        "2026-09-25": {"Ekono": {"Elite United Worlds": _entry(count=2, weighted=5, bounties=1_000)}},
        "2026-09-26": {"EKONO": {"elite united worlds": _entry(count=1, weighted=-1, cz_space_h=2, profit=600_000)}},
    }
    act = faction_activity(report, "ekono", "Elite United Worlds")
    assert act == {"missions": 3, "tier_score": 4, "bounties": 1_000, "combat_bonds": 0, "cz_kills": 2,
                   "trade_profit": 600_000, "exploration": 0, "exobiology": 0}


def test_find_conflict_orients_to_our_faction():
    status = {"conflicts": [_conflict("election", "B", 2, "A", 0)], "faction_states": [], "data_timestamp": "x"}
    c = find_conflict(status, "A", "B", ("election",))
    assert c["days_for"] == 0 and c["days_against"] == 2
    assert find_conflict(status, "A", "B", ("war", "civilwar")) is None
    assert find_conflict(None, "A", "B", ("election",)) is None


# --- Boost ---

def test_boost_todo_with_progress_lines():
    report = {"2026-09-26": {"Ekono": {"EUW": _entry(count=3, weighted=12, bounties=5_000_000, profit=3_400_000)}}}
    history = [
        {"faction_name": "EUW", "snapshot_date": "2026-09-26", "influence": 0.42},
        {"faction_name": "EUW", "snapshot_date": "2026-09-25", "influence": 0.412},
    ]
    view = build_task_view(_task("boost", "EUW"), report, None, history, None, LIMITS)
    assert view["status"] == STATUS_TODO
    assert view["lines"] == [
        "Tier score 12 / 25",
        "Bounties 5.0M / 20.0M",
        "Exploration 0 / 20.0M",
        "Trade profit 3.4M",
        "Influence 41.2% → 42.0% (as of 2026-09-26)",
    ]
    assert view["warnings"] == []
    assert view["hud"] == "Boost EUW — tier score 12/25"


def test_boost_done_when_a_stream_reaches_its_limit_and_warns_past_it():
    report = {"2026-09-26": {"Ekono": {"EUW": _entry(count=6, weighted=27)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["warnings"] == ["Tier score past squadron limit — diminishing returns"]


def test_boost_losing_ground_when_influence_dropped():
    history = [
        {"faction_name": "EUW", "snapshot_date": "2026-09-26", "influence": 0.40},
        {"faction_name": "EUW", "snapshot_date": "2026-09-25", "influence": 0.41},
    ]
    view = build_task_view(_task("boost", "EUW"), {}, None, history, None, LIMITS)
    assert view["status"] == STATUS_LOSING


# --- Vote ---

def _status(*conflicts, ts="2026-09-26T12:00:00Z"):
    return {"conflicts": list(conflicts), "faction_states": [], "data_timestamp": ts}


def test_vote_shows_score_and_counts_non_combat_actions():
    report = {"2026-09-26": {"Kanuket": {"A": _entry(count=2, weighted=4, profit=1_200_000)}}}
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), report,
                           _status(_conflict("election", "A", 2, "B", 0)), [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["lines"][0] == "Days won 2 - 0 (active)"
    assert view["lines"][1] == "Your actions: 2 missions (tier score 4), trade profit 1.2M, exploration 0"
    assert view["hud"] == "Vote A vs B — 2-0"
    assert view["updated_at"] == "2026-09-26T12:00:00Z"


def test_vote_warns_that_combat_does_not_count():
    report = {"2026-09-26": {"Kanuket": {"A": _entry(bonds=50_000)}}}
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), report,
                           _status(_conflict("election", "A", 0, "B", 0)), [], None, LIMITS)
    assert "Combat doesn't count in elections" in view["warnings"]
    assert view["status"] == STATUS_TODO


def test_vote_losing_ground():
    view = build_task_view(_task("vote", "A", "B", system="Kanuket"), {},
                           _status(_conflict("election", "A", 0, "B", 2)), [], None, LIMITS)
    assert view["status"] == STATUS_LOSING


def test_vote_no_data_when_status_older_than_task():
    view = build_task_view(_task("vote", "A", "B", created_at="2026-09-26T13:00:00Z"), {},
                           _status(ts="2026-09-26T12:00:00Z"), [], None, LIMITS)
    assert view["status"] == STATUS_NO_DATA
    assert view["hud"] == "Vote A vs B — no score yet"


def test_vote_ended_when_read_since_task_created_and_gone():
    view = build_task_view(_task("vote", "A", "B", created_at="2026-09-26T11:00:00Z"), {},
                           _status(ts="2026-09-26T12:00:00Z"), [], None, LIMITS)
    assert view["status"] == STATUS_ENDED


# --- Fight ---

def test_fight_counts_combat_actions_and_warns_about_bonds_for_opponent():
    report = {"2026-09-26": {"ICZ": {
        "UID": _entry(cz_space_h=1),
        "Damona": _entry(bonds=80_000),
    }}}
    view = build_task_view(_task("fight", "UID", "Damona", system="ICZ"), report,
                           _status(_conflict("civilwar", "Damona", 0, "UID", 0)), [], None, LIMITS)
    assert view["status"] == STATUS_DONE
    assert view["lines"][0] == "Days won 0 - 0 (active)"
    assert view["lines"][1] == "Your actions: 1 CZ kills, combat bonds 0, 0 missions"
    assert view["warnings"] == ["You cashed combat bonds for Damona"]


# --- PowerPlay / Note ---

def test_powerplay_view():
    pp = {"pp_state": "Unoccupied", "pp_control_progress": 0.789, "pp_controlling_power": None,
          "pp_data_timestamp": "2026-09-26T10:00:00Z"}
    view = build_task_view(_task("powerplay", note="acquisition"), {}, None, [], pp, LIMITS)
    assert view["status"] == STATUS_TRACKING
    assert view["lines"] == ["Unoccupied — 78.9%", "acquisition"]
    assert view["hud"] == "PowerPlay — Unoccupied — 78.9%"
    assert view["updated_at"] == "2026-09-26T10:00:00Z"


def test_powerplay_without_reading():
    view = build_task_view(_task("powerplay"), {}, None, [], None, LIMITS)
    assert view["status"] == STATUS_NO_DATA
    assert view["lines"] == ["No PowerPlay reading yet"]


def test_note_view():
    view = build_task_view(_task("note", note="Undermine in Andel", system=""), {}, None, [], None, LIMITS)
    assert view["status"] == ""
    assert view["lines"] == ["Undermine in Andel"]
    assert view["hud"] == "Note: Undermine in Andel"


# --- HUD line and repo-driven builder ---

def test_hud_line_joins_views():
    assert hud_line([]) == ""
    assert hud_line([{"hud": "Boost A — tier score 1/25"}, {"hud": "Note: x"}]) == \
        "Squadron task: Boost A — tier score 1/25 · Note: x"


def test_build_task_views_filters_by_system_and_uses_repo():
    tasks = [_task("boost", "EUW", address=12345, task_id=1), _task("note", note="x", address=None, system="", task_id=2)]
    calls = []
    repo = SimpleNamespace(
        list_bgs_tasks=lambda: tasks,
        get_session_activity_report=lambda since: calls.append(since) or {},
        get_bgs_status_for_system=lambda addr: None,
        get_faction_history=lambda addr: [],
        get_system_powerplay_snapshot=lambda addr: None,
    )
    views = build_task_views(repo, "2026-09-26T00:00:00Z", LIMITS, system_address=12345)
    assert [v["task"]["id"] for v in views] == [1]
    assert calls == ["2026-09-26T00:00:00Z"]
    assert build_task_views(repo, "t", LIMITS, system_address=999) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_core.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'edc.core.bgs_tasks'`.

- [ ] **Step 3: Implement `edc/core/bgs_tasks.py`**

Create `edc/core/bgs_tasks.py`:

```python
# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""BGS Tasks tracker -- per-task progress and status, derived only from
data the app already records (session activity tables, net.system_bgs_status,
faction_snapshots, systems.pp_*). No task data ever leaves the app. See
docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
from __future__ import annotations

from typing import Optional

TASK_TYPES = ("boost", "vote", "fight", "powerplay", "note")
TASK_LABELS = {"boost": "Boost", "vote": "Vote", "fight": "Fight", "powerplay": "PowerPlay", "note": "Note"}

STATUS_DONE = "Done this tick"
STATUS_TODO = "To do"
STATUS_LOSING = "Losing ground"
STATUS_ENDED = "Conflict ended"
STATUS_NO_DATA = "No data yet"
STATUS_TRACKING = "Tracking"

STATUS_COLORS = {
    STATUS_DONE: "#6BCB77",
    STATUS_TODO: "#c8c8c8",
    STATUS_LOSING: "#FF6B6B",
    STATUS_ENDED: "#888888",
    STATUS_NO_DATA: "#666666",
    STATUS_TRACKING: "#4DD8C8",
}

# Squadron guidance defaults (Frontier publishes no per-stream limits).
DEFAULT_LIMITS = {"tier_score": 25, "bounties": 20_000_000, "exploration": 20_000_000}

_LIMITED_STREAMS = (("tier_score", "Tier score"), ("bounties", "Bounties"), ("exploration", "Exploration"))


def bgs_limits(cfg) -> dict:
    return {
        "tier_score": int(getattr(cfg, "bgs_limit_tier_score", DEFAULT_LIMITS["tier_score"])),
        "bounties": int(getattr(cfg, "bgs_limit_bounties_cr", DEFAULT_LIMITS["bounties"])),
        "exploration": int(getattr(cfg, "bgs_limit_exploration_cr", DEFAULT_LIMITS["exploration"])),
    }


def validate_task_input(system: str, task_type: str, faction: str, opponent: str, note: str) -> str:
    if task_type not in TASK_TYPES:
        return "Pick a task type."
    if task_type != "note" and not system:
        return "Enter a system name."
    if task_type in ("boost", "vote", "fight") and not faction:
        return "Enter the faction to support."
    if task_type in ("vote", "fight") and not opponent:
        return "Enter the opposing faction."
    if task_type == "note" and not note:
        return "Enter the note text."
    return ""


def task_title(task: dict) -> str:
    parts = [TASK_LABELS.get(task["task_type"], task["task_type"])]
    if task.get("faction_name"):
        parts.append(task["faction_name"])
    if task.get("opponent_name"):
        parts.append(f"vs {task['opponent_name']}")
    head = " ".join(parts)
    system = task.get("system_name") or ""
    return f"{system} — {head}" if system else head


def _same(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()


def _cr(value: int) -> str:
    return f"{value / 1_000_000:.1f}M" if abs(value) >= 1_000_000 else f"{value:,}"


def faction_activity(report: dict, system_name: str, faction_name: str) -> dict:
    """This tick's activity for one faction in one system, summed across
    every day in the session report. Names match case-insensitively."""
    total = {k: 0 for k in ("missions", "tier_score", "bounties", "combat_bonds", "cz_kills",
                            "trade_profit", "exploration", "exobiology")}
    for systems in report.values():
        for sys_name, factions in systems.items():
            if not _same(sys_name, system_name):
                continue
            for fac_name, e in factions.items():
                if not _same(fac_name, faction_name):
                    continue
                total["missions"] += e["missions"]["count"]
                total["tier_score"] += e["missions"]["weighted"]
                total["bounties"] += e.get("bounties_total", 0)
                total["combat_bonds"] += e["combat_bonds_total"]
                total["cz_kills"] += sum(e["cz_kills"].values())
                total["trade_profit"] += e["trade_sold"]["commodity"]
                total["exploration"] += e["trade_sold"]["exploration"]
                total["exobiology"] += e["trade_sold"]["exobiology"]
    return total


def find_conflict(bgs_status: Optional[dict], faction_name: str, opponent_name: str, war_types: tuple) -> Optional[dict]:
    """The stored conflict between faction_name and opponent_name (any
    opponent if blank), oriented so "for" is faction_name's side."""
    for c in (bgs_status or {}).get("conflicts") or []:
        if c.get("war_type") not in war_types:
            continue
        f1, f2 = c.get("faction1"), c.get("faction2")
        if _same(f1, faction_name) and (not opponent_name or _same(f2, opponent_name)):
            ours, theirs = "1", "2"
        elif _same(f2, faction_name) and (not opponent_name or _same(f1, opponent_name)):
            ours, theirs = "2", "1"
        else:
            continue
        return {
            "war_type": c.get("war_type"), "status": c.get("status") or "",
            "days_for": c.get(f"won_days{ours}"), "days_against": c.get(f"won_days{theirs}"),
            "stake_for": c.get(f"stake{ours}"), "stake_against": c.get(f"stake{theirs}"),
        }
    return None


def _boost_view(task: dict, report: dict, history: list, limits: dict) -> dict:
    faction = task.get("faction_name") or ""
    act = faction_activity(report, task["system_name"], faction)
    lines = [
        f"Tier score {act['tier_score']} / {limits['tier_score']}",
        f"Bounties {_cr(act['bounties'])} / {_cr(limits['bounties'])}",
        f"Exploration {_cr(act['exploration'])} / {_cr(limits['exploration'])}",
    ]
    if act["trade_profit"]:
        lines.append(f"Trade profit {_cr(act['trade_profit'])}")
    if act["combat_bonds"]:
        lines.append(f"Combat bonds {_cr(act['combat_bonds'])}")
    if act["exobiology"]:
        lines.append(f"Exobiology {_cr(act['exobiology'])}")

    rows = [h for h in history if _same(h.get("faction_name"), faction) and isinstance(h.get("influence"), (int, float))]
    latest = rows[0]["influence"] if rows else None
    previous = rows[1]["influence"] if len(rows) > 1 else None
    as_of = f" (as of {rows[0]['snapshot_date']})" if rows else ""
    if latest is not None and previous is not None:
        lines.append(f"Influence {previous * 100:.1f}% → {latest * 100:.1f}%{as_of}")
    elif latest is not None:
        lines.append(f"Influence {latest * 100:.1f}%{as_of}")

    warnings = [
        f"{label} past squadron limit — diminishing returns"
        for key, label in _LIMITED_STREAMS if limits[key] > 0 and act[key] > limits[key]
    ]
    if any(limits[key] > 0 and act[key] >= limits[key] for key, _ in _LIMITED_STREAMS):
        status = STATUS_DONE
    elif latest is not None and previous is not None and latest < previous:
        status = STATUS_LOSING
    else:
        status = STATUS_TODO
    return {"status": status, "lines": lines, "warnings": warnings,
            "hud": f"Boost {faction} — tier score {act['tier_score']}/{limits['tier_score']}",
            "updated_at": None}


def _conflict_view(task: dict, report: dict, bgs_status: Optional[dict], kind: str) -> dict:
    faction = task.get("faction_name") or ""
    opponent = task.get("opponent_name") or ""
    war_types = ("election",) if kind == "vote" else ("war", "civilwar")
    act = faction_activity(report, task["system_name"], faction)
    c = find_conflict(bgs_status, faction, opponent, war_types)
    updated_at = (bgs_status or {}).get("data_timestamp")
    lines, warnings = [], []

    days_for = days_against = 0
    if c:
        days_for = c["days_for"] if isinstance(c["days_for"], int) else 0
        days_against = c["days_against"] if isinstance(c["days_against"], int) else 0
        lines.append(f"Days won {days_for} - {days_against} ({c['status'] or 'pending'})")
        if c["stake_for"] or c["stake_against"]:
            lines.append(f"Stakes: {c['stake_for'] or 'none'} vs {c['stake_against'] or 'none'}")

    if kind == "vote":
        lines.append(
            f"Your actions: {act['missions']} missions (tier score {act['tier_score']}), "
            f"trade profit {_cr(act['trade_profit'])}, exploration {_cr(act['exploration'])}"
        )
        acted = bool(act["missions"] or act["trade_profit"] > 0 or act["exploration"] or act["exobiology"])
        if act["combat_bonds"] or act["cz_kills"]:
            warnings.append("Combat doesn't count in elections")
    else:
        lines.append(
            f"Your actions: {act['cz_kills']} CZ kills, combat bonds {_cr(act['combat_bonds'])}, "
            f"{act['missions']} missions"
        )
        acted = bool(act["cz_kills"] or act["combat_bonds"] or act["missions"])
        if opponent and faction_activity(report, task["system_name"], opponent)["combat_bonds"]:
            warnings.append(f"You cashed combat bonds for {opponent}")

    if c is None:
        read_since_created = bool(updated_at) and updated_at >= (task.get("created_at") or "")
        status = STATUS_ENDED if read_since_created else STATUS_NO_DATA
    elif acted:
        status = STATUS_DONE
    elif days_against > days_for:
        status = STATUS_LOSING
    else:
        status = STATUS_TODO

    verb = TASK_LABELS[kind]
    who = f"{faction} vs {opponent}" if opponent else faction
    score = f"{days_for}-{days_against}" if c else "no score yet"
    return {"status": status, "lines": lines, "warnings": warnings,
            "hud": f"{verb} {who} — {score}", "updated_at": updated_at}


def _powerplay_view(pp: Optional[dict]) -> dict:
    if not pp:
        return {"status": STATUS_NO_DATA, "lines": ["No PowerPlay reading yet"], "warnings": [],
                "hud": "PowerPlay — no data yet", "updated_at": None}
    reading = pp.get("pp_state") or "Unknown"
    progress = pp.get("pp_control_progress")
    if isinstance(progress, (int, float)):
        reading += f" — {progress * 100:.1f}%"
    lines = [reading]
    if pp.get("pp_controlling_power"):
        lines.append(f"Controlled by {pp['pp_controlling_power']}")
    return {"status": STATUS_TRACKING, "lines": lines, "warnings": [],
            "hud": f"PowerPlay — {reading}", "updated_at": pp.get("pp_data_timestamp")}


def build_task_view(task: dict, report: dict, bgs_status: Optional[dict], history: list,
                    pp: Optional[dict], limits: dict) -> dict:
    task_type = task["task_type"]
    if task_type == "boost":
        view = _boost_view(task, report, history, limits)
    elif task_type in ("vote", "fight"):
        view = _conflict_view(task, report, bgs_status, task_type)
    elif task_type == "powerplay":
        view = _powerplay_view(pp)
    else:
        note = task.get("note") or ""
        return {"task": task, "status": "", "lines": [note] if note else [], "warnings": [],
                "hud": f"Note: {note}" if note else "", "updated_at": None}
    if task.get("note"):
        view["lines"].append(task["note"])
    view["task"] = task
    return view


def build_task_views(repo, since: str, limits: dict, system_address: Optional[int] = None) -> list[dict]:
    """Views for every task (or only those in system_address), in the
    user's priority order."""
    tasks = repo.list_bgs_tasks()
    if system_address is not None:
        tasks = [t for t in tasks if t["system_address"] == system_address]
    if not tasks:
        return []
    report = repo.get_session_activity_report(since)
    views = []
    for t in tasks:
        addr = t["system_address"]
        bgs_status = repo.get_bgs_status_for_system(addr) if addr is not None else None
        history = repo.get_faction_history(addr) if addr is not None else []
        pp = repo.get_system_powerplay_snapshot(addr) if addr is not None else None
        views.append(build_task_view(t, report, bgs_status, history, pp, limits))
    return views


def hud_line(views: list) -> str:
    parts = [v["hud"] for v in views if v.get("hud")]
    return ("Squadron task: " + " · ".join(parts)) if parts else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_core.py -q -p no:cacheprovider`
Expected: PASS. Full suite: only the 3 known failures.

- [ ] **Step 5: Commit**

```bash
git add edc/core/bgs_tasks.py tests/test_bgs_tasks_core.py
git commit -m "feat: BGS task progress and status logic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: BGS Tasks dialog and Player Faction panel button

**Files:**
- Create: `edc/ui/panels/bgs_tasks_dialog.py`
- Modify: `edc/ui/panels/player_faction_panel.py` (import near the existing `from edc.ui.panels.session_activity_dialog import SessionActivityDialog`; class attribute signal next to `tick_refresh_started = pyqtSignal()` ~line 651; `__init__` ~line 660; button after the "Session BGS Activity…" button ~line 833; methods after `_open_session_activity_dialog` ~line 1958)
- Test: `tests/test_bgs_tasks_dialog.py` (create)

**Interfaces:**
- Consumes: Task 2 repository methods; Task 4 `TASK_TYPES`, `TASK_LABELS`, `DEFAULT_LIMITS`, `STATUS_COLORS`, `build_task_views`, `task_title`, `validate_task_input`.
- Produces:
  - `BgsTasksDialog(panel)` — `panel` needs `_repo`, `_latest_known_tick`; optional `bgs_limits_getter` (callable returning the limits dict) and `bgs_tasks_changed` (signal). Public: `refresh()`. Internals used by tests: `_system_edit`, `_type_combo`, `_faction_edit`, `_opponent_edit`, `_note_edit`, `_form_error`, `_cards`, `_on_add()`.
  - `PlayerFactionPanel.bgs_tasks_changed = pyqtSignal()`, `PlayerFactionPanel.bgs_limits_getter` (attribute, default `None`), `PlayerFactionPanel.notify_bgs_activity() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bgs_tasks_dialog.py`:

```python
"""BgsTasksDialog -- add/remove/reorder tasks and render live progress
cards. Real QApplication + real temp-file Repository behind a fake panel,
matching test_session_activity_dialog_render.py's convention."""
import sys
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from edc.ui.panels.bgs_tasks_dialog import BgsTasksDialog
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_app = QApplication.instance() or QApplication(sys.argv)


def _dialog(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (12345, 'Ekono')")
    changed = []
    panel = SimpleNamespace(_repo=repo, _latest_known_tick=None, bgs_limits_getter=None,
                            bgs_tasks_changed=SimpleNamespace(emit=lambda: changed.append(1)))
    return BgsTasksDialog(panel), repo, changed


def _card_texts(dlg):
    return [" | ".join(l.text() for l in card.findChildren(QLabel)) for card in dlg._cards]


def test_add_boost_task_renders_a_card(tmp_path):
    dlg, repo, changed = _dialog(tmp_path)
    dlg._system_edit.setText("ekono")
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("boost"))
    dlg._faction_edit.setText("Elite United Worlds")
    dlg._on_add()
    assert dlg._form_error.text() == ""
    assert len(repo.list_bgs_tasks()) == 1
    assert len(dlg._cards) == 1
    text = _card_texts(dlg)[0]
    assert "Ekono — Boost Elite United Worlds" in text
    assert "Tier score 0 / 25" in text
    assert "To do" in text
    assert dlg._system_edit.text() == ""  # form cleared
    assert changed == [1]


def test_invalid_input_shows_error_and_adds_nothing(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    dlg._system_edit.setText("Kanuket")
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("vote"))
    dlg._faction_edit.setText("Remnants of the Code")
    dlg._on_add()
    assert dlg._form_error.text() == "Enter the opposing faction."
    assert repo.list_bgs_tasks() == []


def test_unknown_system_card_says_not_seen_yet(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    repo.add_bgs_task("Kanuket", "vote", faction_name="A", opponent_name="B")
    dlg.refresh()
    assert "System not seen yet" in _card_texts(dlg)[0]


def test_remove_button_deletes_task(tmp_path):
    dlg, repo, changed = _dialog(tmp_path)
    repo.add_bgs_task("Ekono", "note", note="check in")
    dlg.refresh()
    remove = [b for b in dlg._cards[0].findChildren(QPushButton) if b.text() == "Remove"][0]
    remove.click()
    assert repo.list_bgs_tasks() == []
    assert dlg._cards == []
    assert changed == [1]


def test_move_down_button_reorders(tmp_path):
    dlg, repo, _ = _dialog(tmp_path)
    a = repo.add_bgs_task("Ekono", "note", note="a")
    b = repo.add_bgs_task("Ekono", "note", note="b")
    dlg.refresh()
    down = [btn for btn in dlg._cards[0].findChildren(QPushButton) if btn.text() == "↓"][0]
    down.click()
    assert [t["id"] for t in repo.list_bgs_tasks()] == [b, a]


def test_opponent_field_only_enabled_for_vote_and_fight(tmp_path):
    dlg, _, _ = _dialog(tmp_path)
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("boost"))
    assert not dlg._opponent_edit.isEnabled()
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("fight"))
    assert dlg._opponent_edit.isEnabled()
    dlg._type_combo.setCurrentIndex(dlg._type_combo.findData("note"))
    assert not dlg._faction_edit.isEnabled()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_dialog.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'edc.ui.panels.bgs_tasks_dialog'`.

- [ ] **Step 3: Implement the dialog**

Create `edc/ui/panels/bgs_tasks_dialog.py`:

```python
# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""BGS Tasks -- the squadron's current BGS objectives, entered by hand,
each with live progress from data the app already records. See
docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, STATUS_COLORS, TASK_LABELS, TASK_TYPES, build_task_views, task_title, validate_task_input,
)
from edc.ui import formatting as fmt
from edc.ui.style import CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE

log = logging.getLogger("edc.bgs_tasks")

_LINE_STYLE = "background:transparent; border:none; color:#c8c8c8;"
_DIM_STYLE = "background:transparent; border:none; color:#888888; font-size:11px;"
_WARN_STYLE = "background:transparent; border:none; color:#FFB347;"
_SMALL_BTN = (
    "QPushButton { background:#101c2a; color:#c8c8c8; border:1px solid #2a3a4a;"
    " border-radius:3px; padding:1px 8px; }"
    "QPushButton:hover { background:#1a2a3a; }"
)


class BgsTasksDialog(QDialog):
    """Non-modal window listing every squadron BGS task with its progress."""

    def __init__(self, panel):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self.setWindowTitle("BGS Tasks")
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel("SQUADRON BGS TASKS")
        hdr.setStyleSheet(_HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        form = QHBoxLayout()
        self._system_edit = QLineEdit()
        self._system_edit.setPlaceholderText("System")
        self._type_combo = QComboBox()
        for t in TASK_TYPES:
            self._type_combo.addItem(TASK_LABELS[t], t)
        self._faction_edit = QLineEdit()
        self._faction_edit.setPlaceholderText("Faction to support")
        self._opponent_edit = QLineEdit()
        self._opponent_edit.setPlaceholderText("Opposing faction")
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("Note (optional)")
        add_btn = QPushButton("Add task")
        add_btn.clicked.connect(self._on_add)
        for w in (self._system_edit, self._type_combo, self._faction_edit, self._opponent_edit, self._note_edit):
            form.addWidget(w)
        form.addWidget(add_btn)
        layout.addLayout(form)

        self._form_error = QLabel("")
        self._form_error.setStyleSheet("background:transparent; border:none; color:#FF6B6B;")
        layout.addWidget(self._form_error)

        self._tick_label = QLabel("")
        self._tick_label.setStyleSheet(_DIM_STYLE)
        layout.addWidget(self._tick_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll, 1)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setSpacing(8)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        self._empty_label = QLabel("No tasks yet — add the squadron's objectives above.")
        self._empty_label.setStyleSheet("background:transparent; border:none; color:#666666;")
        self._content_layout.addWidget(self._empty_label)

        footer = QLabel("Boost limits are squadron guidance (editable in Settings), not Frontier numbers.")
        footer.setStyleSheet(_DIM_STYLE)
        layout.addWidget(footer)

        self._cards: list = []
        self._completers_loaded = False
        self._type_combo.currentIndexChanged.connect(self._update_form_fields)
        self._system_edit.editingFinished.connect(self._update_faction_completers)
        self._update_form_fields()

    # ── form ──────────────────────────────────────────────────────────────

    def _update_form_fields(self) -> None:
        t = self._type_combo.currentData()
        self._faction_edit.setEnabled(t in ("boost", "vote", "fight"))
        self._opponent_edit.setEnabled(t in ("vote", "fight"))

    def _make_completer(self, names: list) -> QCompleter:
        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        return completer

    def _load_system_completer(self) -> None:
        try:
            names = self._panel._repo.get_known_system_names()
        except Exception:
            log.exception("Failed to load system names for BGS task entry")
            return
        self._system_edit.setCompleter(self._make_completer(names))
        self._completers_loaded = True

    def _update_faction_completers(self) -> None:
        try:
            resolved = self._panel._repo.resolve_system(self._system_edit.text())
            names = self._panel._repo.get_known_faction_names(resolved[0]) if resolved else []
        except Exception:
            log.exception("Failed to load faction names for BGS task entry")
            return
        self._faction_edit.setCompleter(self._make_completer(names))
        self._opponent_edit.setCompleter(self._make_completer(names))

    def _on_add(self) -> None:
        system = self._system_edit.text().strip()
        task_type = self._type_combo.currentData()
        faction = self._faction_edit.text().strip() if self._faction_edit.isEnabled() else ""
        opponent = self._opponent_edit.text().strip() if self._opponent_edit.isEnabled() else ""
        note = self._note_edit.text().strip()
        error = validate_task_input(system, task_type, faction, opponent, note)
        self._form_error.setText(error)
        if error:
            return
        try:
            self._panel._repo.add_bgs_task(system, task_type, faction or None, opponent or None, note or None)
        except Exception:
            log.exception("Failed to add BGS task")
            self._form_error.setText("Couldn't save the task — see the log.")
            return
        for edit in (self._system_edit, self._faction_edit, self._opponent_edit, self._note_edit):
            edit.clear()
        self.refresh()
        self._changed()

    # ── task actions ─────────────────────────────────────────────────────

    def _changed(self) -> None:
        signal = getattr(self._panel, "bgs_tasks_changed", None)
        if signal is not None:
            signal.emit()

    def _move(self, task_id: int, direction: int) -> None:
        try:
            self._panel._repo.move_bgs_task(task_id, direction)
        except Exception:
            log.exception("Failed to move BGS task")
        self.refresh()
        self._changed()

    def _remove(self, task_id: int) -> None:
        try:
            self._panel._repo.delete_bgs_task(task_id)
        except Exception:
            log.exception("Failed to remove BGS task")
        self.refresh()
        self._changed()

    # ── rendering ────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._completers_loaded:
            self._load_system_completer()
        self.refresh()

    def refresh(self) -> None:
        tick_iso = getattr(self._panel, "_latest_known_tick", None)
        if tick_iso:
            age_txt, _ = fmt.relative_time(tick_iso)
            self._tick_label.setText(f"Your progress since last tick: {age_txt}")
            since = tick_iso
        else:
            self._tick_label.setText("No BGS tick detected yet — progress counts all recorded activity.")
            since = "1970-01-01T00:00:00Z"
        getter = getattr(self._panel, "bgs_limits_getter", None)
        limits = getter() if getter else dict(DEFAULT_LIMITS)
        try:
            views = build_task_views(self._panel._repo, since, limits)
        except Exception:
            log.exception("Failed to build BGS task views")
            views = []
        self._render(views)

    def _render(self, views: list) -> None:
        for card in self._cards:
            self._content_layout.removeWidget(card)
            card.deleteLater()
        self._cards = []
        self._empty_label.setVisible(not views)
        for view in views:
            card = self._make_card(view)
            self._content_layout.addWidget(card)
            self._cards.append(card)

    def _make_card(self, view: dict) -> QFrame:
        task = view["task"]
        card = QFrame()
        card.setStyleSheet(_CARD_STYLE)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(8, 6, 8, 8)
        card_l.setSpacing(3)

        top = QHBoxLayout()
        title = QLabel(task_title(task))
        title.setStyleSheet(_HDR_STYLE)
        title.setWordWrap(True)
        top.addWidget(title, 1)
        if view["status"]:
            status = QLabel(view["status"])
            color = STATUS_COLORS.get(view["status"], "#c8c8c8")
            status.setStyleSheet(f"background:transparent; border:none; color:{color}; font-weight:700;")
            top.addWidget(status)
        task_id = task["id"]
        for text, handler in (
            ("↑", lambda _checked=False, i=task_id: self._move(i, -1)),
            ("↓", lambda _checked=False, i=task_id: self._move(i, +1)),
            ("Remove", lambda _checked=False, i=task_id: self._remove(i)),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(_SMALL_BTN)
            btn.clicked.connect(handler)
            top.addWidget(btn)
        card_l.addLayout(top)

        for line in view["lines"]:
            lbl = QLabel(line)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_LINE_STYLE)
            card_l.addWidget(lbl)
        for warning in view["warnings"]:
            lbl = QLabel(f"⚠ {warning}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_WARN_STYLE)
            card_l.addWidget(lbl)
        if task["system_address"] is None and task["task_type"] != "note":
            lbl = QLabel("System not seen yet — progress appears once you visit it or EDDN reports it.")
            lbl.setStyleSheet(_DIM_STYLE)
            card_l.addWidget(lbl)
        if view.get("updated_at"):
            age_txt, _ = fmt.relative_time(view["updated_at"])
            lbl = QLabel(f"Updated {age_txt}")
            lbl.setStyleSheet(_DIM_STYLE)
            card_l.addWidget(lbl)
        return card
```

- [ ] **Step 4: Wire into the Player Faction panel**

In `edc/ui/panels/player_faction_panel.py`:

Add the import directly below `from edc.ui.panels.session_activity_dialog import SessionActivityDialog`:

```python
from edc.ui.panels.bgs_tasks_dialog import BgsTasksDialog
```

Directly below `tick_refresh_started = pyqtSignal()` in the class body add:

```python
    bgs_tasks_changed = pyqtSignal()
```

In `__init__`, directly below `self._session_activity_dialog = None` add:

```python
        self._bgs_tasks_dialog = None
        # Set by MainWindow: callable returning the Boost limits dict
        # (edc.core.bgs_tasks.bgs_limits(cfg)); None falls back to defaults.
        self.bgs_limits_getter = None
```

Directly below `refresh_row.addWidget(session_activity_btn)` add:

```python
        bgs_tasks_btn = QPushButton("BGS Tasks…")
        bgs_tasks_btn.setStyleSheet(
            "QPushButton { background:#2a1a0d; color:#FFB347; border:1px solid #5a3a1a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a2a1a; }"
        )
        bgs_tasks_btn.setToolTip(
            "Your squadron's BGS objectives, entered by hand, with live progress for each "
            "(influence, conflict score, your actions this tick)."
        )
        bgs_tasks_btn.clicked.connect(self._open_bgs_tasks_dialog)
        refresh_row.addWidget(bgs_tasks_btn)
```

Directly after the `_open_session_activity_dialog` method add:

```python
    def _open_bgs_tasks_dialog(self) -> None:
        if self._bgs_tasks_dialog is None:
            self._bgs_tasks_dialog = BgsTasksDialog(self)
        self._bgs_tasks_dialog.show()
        self._bgs_tasks_dialog.raise_()
        self._bgs_tasks_dialog.activateWindow()

    def notify_bgs_activity(self) -> None:
        """New BGS-relevant data landed (own action, jump, EDDN flush) --
        repaint the BGS Tasks window if it's open. No-op otherwise."""
        dlg = self._bgs_tasks_dialog
        if dlg is not None and dlg.isVisible():
            dlg.refresh()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_tasks_dialog.py -q -p no:cacheprovider`
Expected: PASS. Full suite: only the 3 known failures.

- [ ] **Step 6: Commit**

```bash
git add edc/ui/panels/bgs_tasks_dialog.py edc/ui/panels/player_faction_panel.py tests/test_bgs_tasks_dialog.py
git commit -m "feat: BGS Tasks window opened from the Player Faction panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Overview HUD hint, live refresh wiring, docs

**Files:**
- Modify: `edc/ui/panels/overview_panel.py` (new label directly after the pinned-destination badge block ~line 375; new method after `set_pinned_destination` ~line 505)
- Modify: `edc/ui/main_window.py` (import; module constant; after `self.player_faction_panel = PlayerFactionPanel(...)` ~line 2482; `_on_event` `_BootstrapEnd` branch ~line 3588 and after the `_record_faction_trade_sold` dispatch; `_on_eddn_flush_finished`; two new methods)
- Modify: `tests/test_hud_codex_sightings_cache.py` (fake self gains `_notify_bgs_activity`)
- Modify: `ARCHITECTURE.md`, `README.md`
- Test: `tests/test_bgs_task_hint.py` (create)

**Interfaces:**
- Consumes: Task 3 `AppConfig` limit fields; Task 4 `bgs_limits`, `build_task_views`, `hud_line`; Task 5 `PlayerFactionPanel.bgs_limits_getter`, `bgs_tasks_changed`, `notify_bgs_activity()`.
- Produces: `OverviewPanel.set_bgs_task_hint(text: str) -> None`; `MainWindow._refresh_bgs_task_hint() -> None`; `MainWindow._notify_bgs_activity() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bgs_task_hint.py`:

```python
"""Overview HUD squadron-task hint + MainWindow refresh wiring for the BGS
Tasks tracker."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from edc.config import AppConfig
from edc.ui.main_window import MainWindow
from edc.ui.panels.overview_panel import OverviewPanel
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_app = QApplication.instance() or QApplication(sys.argv)


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (12345, 'Ekono')")
    return repo


def _fake_self(repo, system_address=12345):
    hints = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address),
        repo=repo, cfg=AppConfig(),
        player_faction_panel=SimpleNamespace(_latest_known_tick=None),
        overview_panel=SimpleNamespace(set_bgs_task_hint=hints.append),
        _hints=hints,
    )


def test_hint_shows_task_for_current_system(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    fake_self = _fake_self(repo)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == ["Squadron task: Boost Elite United Worlds — tier score 0/25"]


def test_hint_empty_in_a_system_without_tasks(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("Ekono", "boost", faction_name="Elite United Worlds")
    fake_self = _fake_self(repo, system_address=999)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == [""]


def test_hint_empty_without_a_current_system(tmp_path):
    fake_self = _fake_self(_repo(tmp_path), system_address=None)
    MainWindow._refresh_bgs_task_hint(fake_self)
    assert fake_self._hints == [""]


def test_overview_hint_label_visibility():
    panel = OverviewPanel()
    panel.set_bgs_task_hint("Squadron task: Note: x")
    assert panel.bgs_task_badge.text() == "Squadron task: Note: x"
    assert not panel.bgs_task_badge.isHidden()
    panel.set_bgs_task_hint("")
    assert panel.bgs_task_badge.isHidden()


def test_notify_pushes_panel_and_hint():
    calls = []
    fake_self = SimpleNamespace(
        player_faction_panel=SimpleNamespace(notify_bgs_activity=lambda: calls.append("panel")),
        _refresh_bgs_task_hint=lambda: calls.append("hint"),
    )
    MainWindow._notify_bgs_activity(fake_self)
    assert calls == ["panel", "hint"]


def _dispatch_fake_self(replaying):
    fake_self = MagicMock()
    fake_self._replaying = replaying
    fake_self.engine.process.return_value = (MagicMock(), [])
    fake_self.cfg.eddn_contribute_enabled = False
    return fake_self


def test_activity_event_notifies_when_live():
    fake_self = _dispatch_fake_self(replaying=False)
    MainWindow._on_event(fake_self, {"event": "RedeemVoucher", "Type": "bounty", "Amount": 1, "timestamp": "2026-09-26T10:00:00Z"})
    fake_self._notify_bgs_activity.assert_called_once_with()


def test_activity_event_does_not_notify_during_replay():
    fake_self = _dispatch_fake_self(replaying=True)
    MainWindow._on_event(fake_self, {"event": "FSDJump", "timestamp": "2026-09-26T10:00:00Z"})
    fake_self._notify_bgs_activity.assert_not_called()


def test_bootstrap_end_refreshes_hint():
    fake_self = _dispatch_fake_self(replaying=True)
    MainWindow._on_event(fake_self, {"event": "_BootstrapEnd"})
    fake_self._refresh_bgs_task_hint.assert_called_once_with()
```

In `tests/test_hud_codex_sightings_cache.py`, in `_fake_self`, add this keyword to the `SimpleNamespace(...)` call (e.g. directly after `_notify_calls=notify_calls,`):

```python
        _notify_bgs_activity=lambda: None,
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_task_hint.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: type object 'MainWindow' has no attribute '_refresh_bgs_task_hint'` (and the overview test with `AttributeError: ... 'set_bgs_task_hint'`).

- [ ] **Step 3: Implement the Overview label**

In `edc/ui/panels/overview_panel.py`, directly after `layout.addWidget(self.pinned_destination_badge)` add:

```python
        # ── Squadron BGS task hint (current system has a BGS task) ─────────
        self.bgs_task_badge = QLabel("")
        self.bgs_task_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.bgs_task_badge.setWordWrap(True)
        self.bgs_task_badge.setVisible(False)
        self.bgs_task_badge.setStyleSheet(
            "QLabel { background: #2a1a0d; border: 1px solid #5a3a1a;"
            "border-radius: 6px; padding: 6px 10px; color: #FFB347; }"
        )
        layout.addWidget(self.bgs_task_badge)
```

Directly after the `set_pinned_destination` method add:

```python
    def set_bgs_task_hint(self, text: str) -> None:
        """One line naming the squadron BGS task(s) for the current system,
        or "" to hide. Plain text -- faction names are never parsed as HTML."""
        self.bgs_task_badge.setText(text)
        self.bgs_task_badge.setVisible(bool(text))
```

- [ ] **Step 4: Implement MainWindow wiring**

In `edc/ui/main_window.py`:

Add to the imports (next to the other `edc.core` imports, e.g. after `from edc.core.bgs_tick import fetch_latest_tick`):

```python
from edc.core.bgs_tasks import bgs_limits, build_task_views, hud_line
```

Add this module-level constant directly above `def _retry_once_if_locked`:

```python
# Journal events after which BGS task progress may have changed.
_BGS_ACTIVITY_EVENTS = frozenset({
    "FSDJump", "Location", "CarrierJump", "Docked", "MissionCompleted", "RedeemVoucher",
    "FactionKillBond", "MarketSell", "MultiSellExplorationData", "SellExplorationData", "SellOrganicData",
})
```

Directly after the `self.player_faction_panel = PlayerFactionPanel(...)` statement (the call spanning several lines, ending with `)`), add:

```python
        self.player_faction_panel.bgs_limits_getter = lambda: bgs_limits(self.cfg)
        self.player_faction_panel.bgs_tasks_changed.connect(self._refresh_bgs_task_hint)
```

In `_on_event`, in the `if name == "_BootstrapEnd":` branch, add directly before its `return`:

```python
            self._refresh_bgs_task_hint()
```

In `_on_event`, directly after the block

```python
        if name in ("MarketSell", "MultiSellExplorationData", "SellExplorationData", "SellOrganicData") and not self._replaying:
            self._record_faction_trade_sold(evt)
```

add:

```python
        if name in _BGS_ACTIVITY_EVENTS and not self._replaying:
            self._notify_bgs_activity()
```

At the end of `_on_eddn_flush_finished` (after its last `try/except` block), add:

```python
        self._notify_bgs_activity()
```

Add these two methods directly after `_on_eddn_flush_finished`:

```python
    def _notify_bgs_activity(self) -> None:
        try:
            self.player_faction_panel.notify_bgs_activity()
        except Exception:
            log.exception("Failed to refresh BGS Tasks window")
        self._refresh_bgs_task_hint()

    def _refresh_bgs_task_hint(self) -> None:
        """Overview HUD line for the squadron BGS task(s) in the current
        system -- see docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
        system_address = getattr(self.state, "system_address", None)
        text = ""
        if isinstance(system_address, int):
            try:
                since = getattr(self.player_faction_panel, "_latest_known_tick", None) or "1970-01-01T00:00:00Z"
                views = build_task_views(self.repo, since, bgs_limits(self.cfg), system_address=system_address)
                text = hud_line(views)
            except Exception:
                log.exception("Failed to build BGS task hint")
        self.overview_panel.set_bgs_task_hint(text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bgs_task_hint.py tests/test_hud_codex_sightings_cache.py tests/test_record_session_activity_events.py -q -p no:cacheprovider`
Expected: PASS. Full suite: only the 3 known failures.

- [ ] **Step 6: Update docs**

In `README.md`, in the **Player Faction (BGS)** feature bullet, change the ending `…and a Session BGS Activity Report covering every faction's mission/combat/CZ/trade activity for the whole session, grouped by day` to `…a Session BGS Activity Report covering every faction's mission/combat/CZ/trade activity for the whole session, grouped by day, and a BGS Tasks tracker for your squadron's objectives (Boost/Vote/Fight/PowerPlay) with live per-task progress and an Overview HUD hint`.

In `ARCHITECTURE.md`:
- In the database tables list (next to the `faction_bounties` row), add:
  `| \`bgs_tasks\` | Squadron BGS objectives entered by hand for the BGS Tasks tracker (system, type, faction, opponent, note, priority order); system name resolved to \`system_address\` when first seen |`
- In the modules list, add an entry for `edc/core/bgs_tasks.py`: `Pure logic for the BGS Tasks tracker — per-task progress/status from the session activity tables, \`net.system_bgs_status\` (now including elections), \`faction_snapshots\` and \`systems.pp_*\`; Boost limits are squadron guidance from Settings`.
- In the panels list, next to `session_activity_dialog.py`, add `bgs_tasks_dialog.py`: `BGS Tasks window (from the Player Faction panel) — add/remove/reorder tasks, live progress cards; the current system's task(s) also show as a line on the Overview HUD`.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/overview_panel.py edc/ui/main_window.py tests/test_bgs_task_hint.py tests/test_hud_codex_sightings_cache.py README.md ARCHITECTURE.md
git commit -m "feat: Overview HUD hint and live refresh for BGS tasks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Live verification (after all tasks — project rule)

Not a subagent task. With the app running: open Player Faction → BGS Tasks…, enter the current squadron objectives (Ekono Boost Elite United Worlds; Kanuket Vote Remnants of the Code vs Elite United Worlds; the ICZ Fight; the Tucanae PowerPlay task), then in-game hand in a mission / cash bonds / sell cargo in a task system and confirm the card and the Overview HUD line update.
