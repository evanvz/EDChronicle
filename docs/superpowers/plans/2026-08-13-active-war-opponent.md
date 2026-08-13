# Active War Opponent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Player Faction card's tracked faction is at active War/CivilWar in a system, show who they're at war against and that opponent's influence, instead of a generic "War active" message.

**Architecture:** `Repository.get_faction_predictions()` gains a new `active_war` field per system, computed by checking the tracked faction's own latest state, then (only if at war) looking up which other faction(s) in that system also show a war state — no proximity/influence filtering, since an active war isn't a "close influence" signal the way the existing `conflict_risk` predictor is. `_format_forecast()` in the UI renders this as the new highest-priority line.

**Tech Stack:** Python, SQLite (existing `faction_snapshots` table — no schema change).

## Global Constraints

- `persistence/repository.py` must not import anything from `edc/ui/panels/` — this file already has its own module-level `_parse_states()` helper (line 59) for exactly this reason ("persistence must not depend on the UI layer," per that function's own docstring). The new war-detection logic reuses this existing helper, not a new import.
- War is identified per-faction: a faction's own `faction_state` column equals `"war"`/`"civilwar"` (case-insensitive), OR its `active_states` JSON column (parsed via the existing `_parse_states()`) contains `"war"`/`"civilwar"` (case-insensitive) — this mirrors `_bgs_action_core()`'s existing check in `edc/ui/panels/player_faction_panel.py` (lines ~123-133), duplicated as logic, not imported.
- The opponent lookup is NOT influence-filtered (unlike the existing `conflict_risk` rivals query, which requires `influence >= 0.07` and a small delta) — an active war can exist between factions at very different influence levels (the motivating real case: 60% vs 20%).
- `active_war` shape: `None` (tracked faction not at war) | `{"faction_name": None, "influence": None}` (at war, no other faction in the system currently shows a war state — EDSM data asymmetry) | `{"faction_name": str, "influence": float}` (at war, named opponent found — highest-influence one if multiple factions show war states).
- No new files, no schema changes.

---

## File Structure

- **Modify:** `persistence/repository.py` — new module-level `_row_is_at_war()` helper (next to the existing `_parse_states()`), `get_faction_predictions()` extended with `active_war`.
- **Modify:** `edc/ui/panels/player_faction_panel.py` — `_format_forecast()` gets a new top-priority branch.
- **Test:** `tests/test_active_war_opponent.py` (new) — covers both `get_faction_predictions()`'s new behavior and `_format_forecast()`'s new branch.

---

### Task 1: `Repository.get_faction_predictions()` — `active_war`

**Files:**
- Modify: `persistence/repository.py`
- Test: `tests/test_active_war_opponent.py`

**Interfaces:**
- Produces: `get_faction_predictions()`'s returned dicts gain `"active_war"` — used by Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_active_war_opponent.py`:

```python
"""Tests for Repository.get_faction_predictions()'s active_war field and
player_faction_panel._format_forecast()'s active-war rendering -- real
SQLite (temp file), not mocks, matching this repo's established pattern
(see tests/test_faction_snapshot_freshness.py)."""
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


def _faction(name, influence, faction_state=None, active_states=None):
    f = {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}
    if faction_state is not None:
        f["FactionState"] = faction_state
    if active_states is not None:
        f["ActiveStates"] = active_states
    return f


def _save(repo, system_address, faction, snapshot_date="2026-08-13", is_controlling=True):
    repo.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, snapshot_date, "edsm")


# --- get_faction_predictions() -- active_war ---

def test_war_with_named_opponent(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_detected_via_civilwar_state(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="CivilWar"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="CivilWar"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_detected_via_active_states_not_faction_state(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, active_states=[{"State": "War"}]))
    _save(repo, 1, _faction("Rival Faction", 0.2, active_states=[{"State": "War"}]))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_no_matching_opponent_is_unknown(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Peaceful Faction", 0.2, faction_state="None"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": None, "influence": None}


def test_not_at_war_is_none(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="Boom"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] is None


def test_highest_influence_rival_picked_when_multiple_at_war(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Small Rival", 0.1, faction_state="War"))
    _save(repo, 1, _faction("Big Rival", 0.3, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Big Rival", "influence": 0.3}


def test_low_influence_opponent_found_despite_large_gap(repo):
    # The real case that motivated this feature: 60% vs 20%, nowhere near
    # the existing conflict_risk predictor's 5-point proximity threshold.
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Distant Rival", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"]["faction_name"] == "Distant Rival"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_active_war_opponent.py -v`
Expected: every `active_war`-related test FAILs with `KeyError: 'active_war'`.

- [ ] **Step 3: Add `_row_is_at_war()` next to the existing `_parse_states()`**

Re-read `persistence/repository.py` fresh before editing (confirm `_parse_states()` is still at/near line 59 — it was re-read immediately before this plan was written). Add this new function directly after `_parse_states()`:

```python
def _row_is_at_war(faction_state, active_states) -> bool:
    """True if a faction_snapshots row's own faction_state or active_states
    shows War or CivilWar -- mirrors player_faction_panel.py's
    _bgs_action_core() war check, duplicated as logic (not imported) for
    the same layering reason as _parse_states() above."""
    states = {s.lower() for s in _parse_states(active_states)}
    if isinstance(faction_state, str) and faction_state.strip():
        states.add(faction_state.strip().lower())
    return "war" in states or "civilwar" in states
```

- [ ] **Step 4: Extend `get_faction_predictions()` with `active_war`**

Re-read the current `get_faction_predictions()` method fresh (it was re-read immediately before this plan was written; confirm the `conflict_risk` block still ends around where `out.append({...})` begins, since that's the exact insertion point).

Current code (the tail of the per-system loop, from the `conflict_risk` block through `out.append`):

```python
            conflict_risk = None
            if our_influence is not None and our_influence >= 0.07:
                rivals = self.db.conn.execute(
                    """
                    SELECT fs.faction_name, fs.influence
                    FROM faction_snapshots fs
                    WHERE fs.system_address = ? AND fs.faction_name != ?
                      AND fs.influence IS NOT NULL AND fs.influence >= 0.07
                      AND fs.snapshot_date = (
                          SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                          WHERE fs2.system_address = fs.system_address
                            AND fs2.faction_name = fs.faction_name
                      )
                    """,
                    (system_address, faction_name),
                ).fetchall()
                best, best_diff = None, None
                for r in rivals:
                    diff = abs(r["influence"] - our_influence)
                    if diff <= 0.05 and (best_diff is None or diff < best_diff):
                        best, best_diff = r, diff
                if best is not None:
                    conflict_risk = {
                        "faction_name": best["faction_name"],
                        "influence": best["influence"],
                        "diff": best_diff,
                    }

            out.append({
                "system_address": system_address,
                "system_name": system_name,
                "influence": our_influence,
                "trend": trend,
                "days_in_expansion_range": days_in_expansion_range,
                "days_in_retreat_range": days_in_retreat_range,
                "conflict_risk": conflict_risk,
            })
        return out
```

Replace with (adds the `active_war` computation between `conflict_risk` and `out.append`, and adds `"active_war": active_war` to the appended dict):

```python
            conflict_risk = None
            if our_influence is not None and our_influence >= 0.07:
                rivals = self.db.conn.execute(
                    """
                    SELECT fs.faction_name, fs.influence
                    FROM faction_snapshots fs
                    WHERE fs.system_address = ? AND fs.faction_name != ?
                      AND fs.influence IS NOT NULL AND fs.influence >= 0.07
                      AND fs.snapshot_date = (
                          SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                          WHERE fs2.system_address = fs.system_address
                            AND fs2.faction_name = fs.faction_name
                      )
                    """,
                    (system_address, faction_name),
                ).fetchall()
                best, best_diff = None, None
                for r in rivals:
                    diff = abs(r["influence"] - our_influence)
                    if diff <= 0.05 and (best_diff is None or diff < best_diff):
                        best, best_diff = r, diff
                if best is not None:
                    conflict_risk = {
                        "faction_name": best["faction_name"],
                        "influence": best["influence"],
                        "diff": best_diff,
                    }

            active_war = None
            own_row = self.db.conn.execute(
                """
                SELECT faction_state, active_states
                FROM faction_snapshots
                WHERE system_address = ? AND faction_name = ?
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (system_address, faction_name),
            ).fetchone()
            if own_row is not None and _row_is_at_war(own_row["faction_state"], own_row["active_states"]):
                war_rivals = self.db.conn.execute(
                    """
                    SELECT fs.faction_name, fs.influence, fs.faction_state, fs.active_states
                    FROM faction_snapshots fs
                    WHERE fs.system_address = ? AND fs.faction_name != ?
                      AND fs.snapshot_date = (
                          SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                          WHERE fs2.system_address = fs.system_address
                            AND fs2.faction_name = fs.faction_name
                      )
                    """,
                    (system_address, faction_name),
                ).fetchall()
                best_opponent = None
                for r in war_rivals:
                    if not _row_is_at_war(r["faction_state"], r["active_states"]):
                        continue
                    r_influence = r["influence"] if isinstance(r["influence"], (int, float)) else 0.0
                    best_influence = best_opponent["influence"] if best_opponent and isinstance(best_opponent["influence"], (int, float)) else -1.0
                    if best_opponent is None or r_influence > best_influence:
                        best_opponent = r
                if best_opponent is not None:
                    active_war = {"faction_name": best_opponent["faction_name"], "influence": best_opponent["influence"]}
                else:
                    active_war = {"faction_name": None, "influence": None}

            out.append({
                "system_address": system_address,
                "system_name": system_name,
                "influence": our_influence,
                "trend": trend,
                "days_in_expansion_range": days_in_expansion_range,
                "days_in_retreat_range": days_in_retreat_range,
                "conflict_risk": conflict_risk,
                "active_war": active_war,
            })
        return out
```

Also update the method's docstring (directly above it) to mention the new field — find the line `conflict_risk (None or {"faction_name", "influence", "diff"})` in the docstring and add a line after it:

```
          active_war (None, or {"faction_name", "influence"} where
          faction_name/influence are None if no opponent could be
          identified)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_active_war_opponent.py -v`
Expected: all 7 tests written so far PASS.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: all previously-passing tests plus these 7 new ones pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add persistence/repository.py tests/test_active_war_opponent.py
git commit -m "feat: identify the active-war opponent faction in get_faction_predictions()"
```

---

### Task 2: `_format_forecast()` — render the active-war line

**Files:**
- Modify: `edc/ui/panels/player_faction_panel.py`
- Test: `tests/test_active_war_opponent.py` (same file as Task 1, new test functions appended)

**Interfaces:**
- Consumes: `prediction["active_war"]` — `None` | `{"faction_name": None, "influence": None}` | `{"faction_name": str, "influence": float}` (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_active_war_opponent.py` (same file, add these functions and the needed import at the top):

```python
from edc.ui.panels.player_faction_panel import _format_forecast


# --- _format_forecast() -- active_war rendering ---

def test_forecast_shows_named_war_opponent():
    prediction = {"active_war": {"faction_name": "Rival Faction", "influence": 0.2}}
    text, color = _format_forecast(prediction)
    assert text == "⚔ At War vs Rival Faction (20.0%)"
    assert color == "#FF6B6B"


def test_forecast_shows_unknown_war_opponent():
    prediction = {"active_war": {"faction_name": None, "influence": None}}
    text, color = _format_forecast(prediction)
    assert text == "⚔ At War — opponent unknown (EDSM data incomplete)"
    assert color == "#FF6B6B"


def test_forecast_falls_through_to_conflict_risk_when_not_at_war():
    # No-regression check: active_war absent/None must not disturb the
    # pre-existing conflict_risk branch.
    prediction = {
        "active_war": None,
        "conflict_risk": {"faction_name": "Close Rival", "diff": 0.03},
    }
    text, color = _format_forecast(prediction)
    assert text == "⚔ Conflict risk vs Close Rival (Δ3.0%)"
    assert color == "#FFB347"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_active_war_opponent.py -v`
Expected: the 3 new tests FAIL — `test_forecast_shows_named_war_opponent` and `test_forecast_shows_unknown_war_opponent` fail because `_format_forecast` doesn't yet look at `active_war` at all (falls through to the `"—"`/no-prediction-data path or raises depending on what other keys are missing); `test_forecast_falls_through_to_conflict_risk_when_not_at_war` should already PASS since it only exercises the pre-existing `conflict_risk` path — if it doesn't, that's a sign the fixture prediction dict is missing a key `_format_forecast` currently expects; adjust the test dict, not the source, if so (don't change source to accommodate a wrong test).

- [ ] **Step 3: Add the active-war branch to `_format_forecast()`**

Re-read `edc/ui/panels/player_faction_panel.py` fresh before editing (confirm `_format_forecast()`'s current body still matches — it was re-read immediately before this plan was written).

Current code:

```python
def _format_forecast(prediction: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Returns (text, color_hex) for the Forecast column, from a
    Repository.get_faction_predictions() entry. Priority: conflict risk
    (a rival converging on your influence) > expansion/retreat risk (both
    are "impending event" signals from the real BGS thresholds) > plain
    trend > "not enough history yet"."""
    if not prediction:
        return ("—", "#7a7a7a")

    conflict = prediction.get("conflict_risk")
    if conflict:
```

Replace with (adds the `active_war` check as the first branch, updates the docstring's priority list):

```python
def _format_forecast(prediction: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Returns (text, color_hex) for the Forecast column, from a
    Repository.get_faction_predictions() entry. Priority: active war (it
    already happened, outranks a mere risk prediction) > conflict risk
    (a rival converging on your influence) > expansion/retreat risk (both
    are "impending event" signals from the real BGS thresholds) > plain
    trend > "not enough history yet"."""
    if not prediction:
        return ("—", "#7a7a7a")

    active_war = prediction.get("active_war")
    if active_war:
        opponent = active_war.get("faction_name")
        if opponent:
            influence_pct = (active_war.get("influence") or 0.0) * 100
            return (f"⚔ At War vs {opponent} ({influence_pct:.1f}%)", "#FF6B6B")
        return ("⚔ At War — opponent unknown (EDSM data incomplete)", "#FF6B6B")

    conflict = prediction.get("conflict_risk")
    if conflict:
```

(Everything after the `if conflict:` line is unchanged — do not modify it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_active_war_opponent.py -v`
Expected: all 10 tests (7 from Task 1 + 3 from this task) PASS.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Byte-compile check**

Run: `python -m py_compile persistence/repository.py edc/ui/panels/player_faction_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/player_faction_panel.py tests/test_active_war_opponent.py
git commit -m "feat: show the active-war opponent on the Player Faction card's Forecast column"
```
