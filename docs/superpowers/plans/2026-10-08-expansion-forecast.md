# Expansion Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show where the squadron faction's next BGS expansion is likely to land (ranked shortlist), where the last one landed, and alert when the faction appears in a new system.

**Architecture:** A new pure-logic module `edc/core/expansion_forecast.py` holds the rules (watched systems, likely source, ±20 ly cube, tier ranking, new-system detection, and the expansion-ending detection moved out of the dialog). The repository gets a small cache table plus read queries. A new `ExpansionForecastPanel` widget becomes the second tab of the existing Faction Expansion Tracker; its background worker runs the slow cube query and the EDSM lookups on its own DB connection. The new-system alert shows on the Overview and in the Session BGS Activity Report.

**Tech Stack:** Python 3.12, PyQt6, SQLite (main DB + attached `net` cache DB), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-expansion-forecast-design.md`

## Global Constraints

- Run tests with: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider` (set `QT_QPA_PLATFORM=offscreen` in Git Bash). The full suite must stay green (1330 passing before this plan).
- SQLite connections cannot be shared across threads — a worker opens its own `Database(db_path)` and closes it in `finally`.
- QThread objects stay referenced on `self` for their lifetime; never `wait()` a thread from a slot it signals — connect `finished` to `thread.quit` instead.
- The faction is never hard-coded: use `PlayerFactionPanel._faction_name`, falling back to `Repository.get_squadron_faction_name()`.
- Thresholds (verbatim from the spec): watch ≥ 70% influence; expansion source ≥ 75% for at least a day; cube ±20 ly per axis; look up the nearest 10 candidates; cache refreshed at most once a day; new-system alert shown for 3 days; a "new" system's first influence is above 0 and at most 20%.
- Game rules are community-researched (squad bot's `docs/expansion-logic.md`, Complete BGS Guide 2025 pp. 63–67; SINC 2024) — label them as such in UI text, never as Frontier fact.
- Every rich-text label built from system/faction names uses `html.escape()` (names come from EDDN). Plain-text labels need no escaping.
- Commits: message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Git pushes from Git Bash are blocked by Application Control here; push from PowerShell. Do not push without the user's OK.

## Review Focus

1. **No squadron faction known** (fresh install, never docked at a squadron station) → the Forecast tab says "No squadron faction known yet." and nothing crashes; the Overview alert stays hidden. Test in Task 3 and Task 4.
2. **EDSM lookup failing or blocked** for some candidates → those rows show "not checked", ranked ones still show, the previous cache is kept. Test in Task 3 (worker result with a `None` faction count) and Task 1 (ranking puts unchecked last).
3. **Old rows of a system the faction left long ago** (influence 0 or last seen weeks ago) → never count as "current", never trigger the new-system alert, and do count as "been there before". Tests in Task 1.
4. **A long-held system fetched for the first time** (e.g. an EDSM refresh adds a system the faction has held for months, first snapshot today at 45%) → not reported as new because of the 20% cap. Test in Task 1.
5. **No watched system at 70%** (all faction systems below) → "No faction system at 70% or more." and no lookup worker starts. Test in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `edc/core/expansion_forecast.py` (create) | Pure rules: state parsing, expansion endings/phase, days ≥75%, watched systems, likely source, cube test, tier ranking, new-system detection, alert text; one thin `detect_new_systems(repo, …)` wrapper |
| `edc/ui/panels/faction_expansion_dialog.py` (modify) | Import the moved helpers; wrap existing content as tab 1; add the Forecast tab |
| `persistence/database.py` (modify) | `expansion_candidates` table in the main-DB migration list |
| `persistence/repository.py` (modify) | `get_squadron_presence`, `get_cube_systems`, `save_expansion_candidates`, `get_expansion_candidates` |
| `edc/ui/panels/expansion_forecast_panel.py` (create) | Forecast tab widget + its background worker |
| `edc/ui/panels/overview_panel.py` (modify) | `new_system_badge` + `set_new_system_alert(text)` |
| `edc/ui/main_window.py` (modify) | `_refresh_new_system_alert()` on startup and on BGS activity |
| `edc/ui/panels/session_activity_dialog.py` (modify) | New-system line under the header |
| `README.md`, `ARCHITECTURE.md` (modify) | Describe the feature |
| `tests/test_expansion_forecast.py` (create) | Core rules |
| `tests/test_expansion_forecast_repo.py` (create) | Repository queries and cache |
| `tests/test_expansion_forecast_panel.py` (create) | Forecast tab render + alert wiring |

---

### Task 1: Core rules module

**Files:**
- Create: `edc/core/expansion_forecast.py`
- Modify: `edc/ui/panels/faction_expansion_dialog.py` (remove `_parse_states`, `_is_expanding`, `expansion_endings` bodies; import from the new module)
- Test: `tests/test_expansion_forecast.py` (create); `tests/test_expansion_endings.py` must keep passing unchanged

**Interfaces:**
- Consumes: nothing new.
- Produces (exact names, used by Tasks 3 and 4):
  - `WATCH_THRESHOLD = 0.70`, `EXPANSION_THRESHOLD = 0.75`, `CUBE_LY = 20.0`, `LOOKUP_COUNT = 10`, `NEW_SYSTEM_DAYS = 3`, `NEW_SYSTEM_MAX_INFLUENCE = 0.20`, `CURRENT_DAYS = 14`, `CACHE_MAX_AGE_H = 24`
  - `parse_states(raw) -> list[str]`, `is_expanding(snap: dict | None) -> bool`, `expansion_endings(history_asc: list[dict]) -> list[tuple[int, str, float]]`
  - `expansion_phase(snap: dict) -> str` ("active" / "pending" / "recovering" / "")
  - `days_at_or_above(history_asc: list[dict], threshold: float = EXPANSION_THRESHOLD) -> int`
  - `is_current(row: dict, today: date) -> bool`
  - `watched_systems(presence: list[dict], histories: dict[int, list[dict]], today: date) -> list[dict]` (presence rows plus `days_above`, `phase`; sorted by influence, highest first)
  - `likely_source(watched: list[dict]) -> dict | None` (adds `eligible: bool`)
  - `in_cube(src: tuple, xyz: tuple, half: float = CUBE_LY) -> bool`
  - `rank_candidates(cands: list[dict]) -> list[dict]` (input keys: `system_name`, `distance_ly`, `faction_count` (int or None), `faction_present` (bool), `been_before` (bool); adds `tier`: 1/2/3 or None)
  - `new_systems(presence: list[dict], endings: list[tuple[str, str]], today: date, days: int = NEW_SYSTEM_DAYS) -> list[dict]` (`system_name`, `influence`, `first_seen`, `source`)
  - `alert_text(faction: str, item: dict) -> str`
  - `detect_new_systems(repo, faction: str, today: date | None = None) -> list[dict]`
  - Presence row keys (produced by Task 2's `get_squadron_presence`): `system_address`, `system_name`, `first_seen`, `last_seen`, `influence`, `faction_state`, `active_states`, `pending_states`, `recovering_states`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expansion_forecast.py`:

```python
"""Expansion Forecast rules (edc/core/expansion_forecast.py). Real data from
2026-10-07/08: Ekono expanded into Tucanae Sector YF-W b2-2; Arimavante was
closer with 6 factions but was skipped (likely an earlier EUW retreat)."""
from datetime import date

from edc.core import expansion_forecast as ef

R = '[{"State": "Expansion", "Trend": 0}]'
TODAY = date(2026, 10, 8)


def _p(addr, name, inf, first, last, **states):
    return {"system_address": addr, "system_name": name, "influence": inf, "first_seen": first,
            "last_seen": last, "faction_state": states.get("state"), "active_states": states.get("active"),
            "pending_states": states.get("pending"), "recovering_states": states.get("rec")}


def test_in_cube_uses_each_axis_not_straight_line():
    ekono = (59.125, -155.15625, 99.8125)
    yfw = (39.46875, -163.9375, 117.96875)            # 28.2 ly away, every axis under 20
    assert ef.in_cube(ekono, yfw)
    assert not ef.in_cube(ekono, (59.125 + 21, -155.15625, 99.8125))


def test_days_at_or_above_counts_the_latest_run():
    hist = [{"influence": 0.80}, {"influence": 0.70}, {"influence": 0.76}, {"influence": 0.79}]
    assert ef.days_at_or_above(hist) == 2
    assert ef.days_at_or_above([{"influence": 0.6}]) == 0


def test_expansion_phase():
    assert ef.expansion_phase({"pending_states": R}) == "pending"
    assert ef.expansion_phase({"faction_state": "Expansion", "active_states": '[{"State": "Expansion"}]'}) == "active"
    # 2026-09-23: state still read Expansion but it was recovering
    assert ef.expansion_phase({"faction_state": "Expansion", "recovering_states": R}) == "recovering"
    assert ef.expansion_phase({}) == ""


def test_watched_and_likely_source():
    presence = [_p(1, "Ekono", 0.7895, "2026-09-08", "2026-10-06"),
                _p(2, "Other", 0.72, "2026-09-08", "2026-10-07"),
                _p(3, "Low", 0.40, "2026-09-08", "2026-10-07"),
                _p(4, "Left long ago", 0.90, "2026-08-01", "2026-08-20")]   # not current
    hist = {1: [{"influence": 0.80}, {"influence": 0.7895}], 2: [{"influence": 0.72}]}
    watched = ef.watched_systems(presence, hist, TODAY)
    assert [w["system_name"] for w in watched] == ["Ekono", "Other"]
    src = ef.likely_source(watched)
    assert src["system_name"] == "Ekono" and src["eligible"] is True
    only_low = ef.watched_systems([_p(2, "Other", 0.72, "2026-09-08", "2026-10-07")], {2: [{"influence": 0.72}]}, TODAY)
    assert ef.likely_source(only_low)["eligible"] is False
    assert ef.likely_source([]) is None


def test_old_or_zero_rows_are_not_current():
    assert not ef.is_current(_p(1, "A", 0.5, "2026-08-01", "2026-09-01"), TODAY)   # last seen > 14 days ago
    assert not ef.is_current(_p(1, "A", 0.0, "2026-08-01", "2026-10-07"), TODAY)   # influence 0 = left
    assert ef.is_current(_p(1, "A", 0.5, "2026-08-01", "2026-10-07"), TODAY)


def test_rank_candidates_tiers_and_order():
    cands = [
        {"system_name": "YF-W", "distance_ly": 28.2, "faction_count": 4, "faction_present": False, "been_before": False},
        {"system_name": "Arimavante", "distance_ly": 10.9, "faction_count": 6, "faction_present": False, "been_before": False},
        {"system_name": "Left before", "distance_ly": 5.0, "faction_count": 5, "faction_present": False, "been_before": True},
        {"system_name": "Seven", "distance_ly": 3.0, "faction_count": 7, "faction_present": False, "been_before": False},
        {"system_name": "Eight", "distance_ly": 2.0, "faction_count": 8, "faction_present": False, "been_before": False},
        {"system_name": "Here now", "distance_ly": 1.0, "faction_count": 3, "faction_present": True, "been_before": False},
        {"system_name": "Not checked", "distance_ly": 4.0, "faction_count": None, "faction_present": False, "been_before": False},
    ]
    out = ef.rank_candidates(cands)
    assert [(c["system_name"], c["tier"]) for c in out] == [
        ("Arimavante", 1), ("YF-W", 1), ("Left before", 2), ("Seven", 3), ("Not checked", None)]


def test_new_system_paired_with_expansion_ending():
    presence = [_p(2, "Tucanae Sector YF-W b2-2", 0.090992, "2026-10-07", "2026-10-07"),
                _p(1, "Ekono", 0.6789, "2026-09-08", "2026-10-07")]
    out = ef.new_systems(presence, [("Ekono", "2026-10-07")], TODAY)
    assert out == [{"system_name": "Tucanae Sector YF-W b2-2", "influence": 0.090992,
                    "first_seen": "2026-10-07", "source": "Ekono"}]
    assert ef.alert_text("Elite United Worlds", out[0]) == (
        "🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%) — likely expansion from Ekono")


def test_new_system_rules_out_old_large_and_zero():
    presence = [_p(1, "Old", 0.09, "2026-10-01", "2026-10-07"),           # first seen 7 days ago
                _p(2, "Long held, first fetch", 0.45, "2026-10-08", "2026-10-08"),   # over the 20% cap
                _p(3, "Left", 0.0, "2026-10-08", "2026-10-08")]
    assert ef.new_systems(presence, [], TODAY) == []
    lone = ef.new_systems([_p(4, "No source", 0.05, "2026-10-08", "2026-10-08")], [], TODAY)
    assert lone[0]["source"] is None
    assert ef.alert_text("EUW", lone[0]) == "🆕 EUW entered No source (5.0%)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'edc.core.expansion_forecast'`.

- [ ] **Step 3: Create the module**

Create `edc/core/expansion_forecast.py`:

```python
# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.
"""Expansion Forecast: where the squadron faction's next BGS expansion is
likely to land, and where the last one landed. Rules are community-
researched (squad bot's docs/expansion-logic.md, Complete BGS Guide 2025
pp. 63-67; SINC 2024), not Frontier documentation.
See docs/superpowers/specs/2026-10-08-expansion-forecast-design.md."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

WATCH_THRESHOLD = 0.70
EXPANSION_THRESHOLD = 0.75
CUBE_LY = 20.0
LOOKUP_COUNT = 10
NEW_SYSTEM_DAYS = 3
NEW_SYSTEM_MAX_INFLUENCE = 0.20   # heuristic: an expansion arrives small (YF-W 9.1%)
CURRENT_DAYS = 14                 # a presence older than this is treated as "left"
CACHE_MAX_AGE_H = 24


def parse_states(raw) -> List[str]:
    """faction_snapshots state-list JSON ([{"State": ...}, ...]) -> state names."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(s.get("State")) for s in data if isinstance(s, dict) and s.get("State")]


def is_expanding(snap: Optional[Dict[str, Any]]) -> bool:
    """Frontier's own "Expansion" state as the faction state or in active_states."""
    if not snap:
        return False
    if (snap.get("faction_state") or "").strip().lower() == "expansion":
        return True
    return "expansion" in {s.lower() for s in parse_states(snap.get("active_states"))}


def expansion_endings(history_asc: List[Dict[str, Any]]) -> List[tuple]:
    """[(index, snapshot_date, influence change in points)] for each day an
    expansion ended: the first day "Expansion" shows under recovering
    states (faction_state can still read "Expansion" that day, and not every
    source carries the state lists, so this is the reliable signal). A
    finished expansion usually costs the home system its "expansion tax",
    about 15% (SINC Complete BGS Guide 2024, p48/53): Ekono lost 14.8 on
    2026-09-23 and 11.1 on 2026-10-07 -- but endings on 2026-08-09 and
    09-11 showed no drop, so the change is reported, not assumed."""
    out = []
    for i in range(1, len(history_asc)):
        prev, cur = history_asc[i - 1], history_asc[i]
        if ("Expansion" in parse_states(cur.get("recovering_states"))
                and "Expansion" not in parse_states(prev.get("recovering_states"))):
            delta = ((cur.get("influence") or 0.0) - (prev.get("influence") or 0.0)) * 100.0
            out.append((i, cur.get("snapshot_date"), delta))
    return out


def expansion_phase(snap: Dict[str, Any]) -> str:
    if "Expansion" in parse_states(snap.get("recovering_states")):
        return "recovering"
    if is_expanding(snap):
        return "active"
    if "Expansion" in parse_states(snap.get("pending_states")):
        return "pending"
    return ""


def days_at_or_above(history_asc: List[Dict[str, Any]], threshold: float = EXPANSION_THRESHOLD) -> int:
    """Consecutive latest snapshots at or above `threshold`."""
    n = 0
    for snap in reversed(history_asc):
        if (snap.get("influence") or 0.0) < threshold:
            break
        n += 1
    return n


def is_current(row: Dict[str, Any], today: date) -> bool:
    """Still present: influence above 0 and seen within CURRENT_DAYS."""
    last = row.get("last_seen")
    if not last or (row.get("influence") or 0.0) <= 0:
        return False
    return (today - date.fromisoformat(str(last)[:10])).days <= CURRENT_DAYS


def watched_systems(presence: List[Dict[str, Any]], histories: Dict[int, List[Dict[str, Any]]],
                    today: date) -> List[Dict[str, Any]]:
    out = []
    for r in presence:
        if not is_current(r, today) or (r.get("influence") or 0.0) < WATCH_THRESHOLD:
            continue
        hist = histories.get(r["system_address"]) or []
        out.append({**r, "days_above": days_at_or_above(hist),
                    "phase": expansion_phase(hist[-1] if hist else r)})
    return sorted(out, key=lambda w: -(w.get("influence") or 0.0))


def likely_source(watched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Highest influence among systems at or above 75% for at least a day;
    otherwise the highest watched system, marked not yet eligible."""
    eligible = [w for w in watched if w["days_above"] >= 1]
    if eligible:
        return {**eligible[0], "eligible": True}
    return {**watched[0], "eligible": False} if watched else None


def in_cube(src: tuple, xyz: tuple, half: float = CUBE_LY) -> bool:
    """Expansion searches a cube (each axis within `half`), not a sphere."""
    return all(abs(a - b) <= half for a, b in zip(src, xyz))


def rank_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tier 1: <7 factions, no known history; tier 2: <7, faction was there
    before; tier 3: exactly 7 (invasion war). 8+ and systems where the
    faction is present now are dropped; not-looked-up rows go last."""
    ranked, unchecked = [], []
    for c in cands:
        if c.get("faction_present"):
            continue
        n = c.get("faction_count")
        if n is None:
            unchecked.append({**c, "tier": None})
            continue
        if n >= 8:
            continue
        tier = 3 if n == 7 else (2 if c.get("been_before") else 1)
        ranked.append({**c, "tier": tier})
    ranked.sort(key=lambda c: (c["tier"], c.get("distance_ly") or 0.0))
    unchecked.sort(key=lambda c: c.get("distance_ly") or 0.0)
    return ranked + unchecked


def new_systems(presence: List[Dict[str, Any]], endings: List[tuple], today: date,
                days: int = NEW_SYSTEM_DAYS) -> List[Dict[str, Any]]:
    """Systems the faction first appeared in within `days`, small (<= 20%),
    paired with an expansion ending within +-1 day: endings are
    [(source system name, "YYYY-MM-DD"), ...]."""
    out = []
    for r in presence:
        first, inf = r.get("first_seen"), r.get("influence") or 0.0
        if not first or not 0 < inf <= NEW_SYSTEM_MAX_INFLUENCE:
            continue
        seen = date.fromisoformat(str(first)[:10])
        if seen > today or (today - seen).days > days:
            continue
        source = next((name for name, d in endings
                       if name != r.get("system_name")
                       and abs((date.fromisoformat(str(d)[:10]) - seen).days) <= 1), None)
        out.append({"system_name": r.get("system_name"), "influence": inf,
                    "first_seen": str(first)[:10], "source": source})
    return sorted(out, key=lambda x: x["first_seen"], reverse=True)


def alert_text(faction: str, item: Dict[str, Any]) -> str:
    src = f" — likely expansion from {item['source']}" if item.get("source") else ""
    return f"🆕 {faction} entered {item['system_name']} ({item['influence'] * 100:.1f}%){src}"


def detect_new_systems(repo, faction: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """new_systems() from the repository: expansion endings are only looked
    for in faction systems at 50%+ (a source sits near 60-70% after paying
    the expansion tax), to keep it to a few history queries."""
    today = today or date.today()
    presence = repo.get_squadron_presence(faction)
    endings = []
    for r in presence:
        if (r.get("influence") or 0.0) >= 0.5:
            hist = list(reversed(repo.get_faction_history(r["system_address"], faction)))
            endings += [(r["system_name"], d) for _i, d, _delta in expansion_endings(hist)]
    return new_systems(presence, endings, today)
```

- [ ] **Step 4: Point the dialog at the moved helpers**

In `edc/ui/panels/faction_expansion_dialog.py`, delete the bodies of `_parse_states` (the function starting `def _parse_states(raw) -> List[str]:`), `_is_expanding` (starting `def _is_expanding(latest_snapshot`), and `expansion_endings` (starting `def expansion_endings(history_asc`), and add after the existing `from edc.core.edsm_faction_lookup import ...` line:

```python
from edc.core.expansion_forecast import (
    expansion_endings, is_expanding as _is_expanding, parse_states as _parse_states,
)
```

`tests/test_expansion_endings.py` imports `expansion_endings` from the dialog module, so it keeps working through this import.

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast.py tests/test_expansion_endings.py -q -p no:cacheprovider`
Expected: all PASS. Then the full suite: all PASS.

- [ ] **Step 6: Commit**

```bash
git add edc/core/expansion_forecast.py edc/ui/panels/faction_expansion_dialog.py tests/test_expansion_forecast.py
git commit -m "feat: expansion forecast rules (cube, tiers, likely source, new-system detection)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Repository queries and candidate cache

**Files:**
- Modify: `persistence/database.py` (main-DB migration list — the list that already holds `CREATE TABLE IF NOT EXISTS pp_control_history`)
- Modify: `persistence/repository.py` (add four methods next to `get_faction_history`)
- Test: `tests/test_expansion_forecast_repo.py` (create)

**Interfaces:**
- Consumes: Task 1's presence-row key names.
- Produces:
  - `Repository.get_squadron_presence(faction: str) -> list[dict]` (keys: `system_address`, `system_name`, `first_seen`, `last_seen`, `influence`, `faction_state`, `active_states`, `pending_states`, `recovering_states`)
  - `Repository.get_cube_systems(x: float, y: float, z: float, half: float) -> list[dict]` (keys: `system_name`, `x`, `y`, `z`, `system_address`, `population`; `population`/`system_address` None when unknown)
  - `Repository.save_expansion_candidates(source_address: int, rows: list[dict], fetched_at: str) -> None` (row keys: `system_name`, `system_address`, `distance_ly`, `faction_count`, `faction_present`)
  - `Repository.get_expansion_candidates(source_address: int) -> list[dict]` (same keys plus `fetched_at`; `faction_present` as bool)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expansion_forecast_repo.py`:

```python
"""Repository side of the Expansion Forecast: faction presence summary,
cube systems with population, and the candidate cache."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

EUW = "Elite United Worlds"


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _snap(repo, addr, date_, inf, rec=None):
    f = {"Name": EUW, "Influence": inf}
    if rec:
        f["RecoveringStates"] = rec
    repo.save_faction_snapshot(addr, f, date_, True, f"{date_}T12:00:00Z", "edsm")


def test_presence_has_first_and_latest_reading(tmp_path):
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Ekono'), (2, 'YF-W')")
    _snap(repo, 1, "2026-10-06", 0.7895)
    _snap(repo, 1, "2026-10-07", 0.6789, [{"State": "Expansion", "Trend": 0}])
    _snap(repo, 2, "2026-10-07", 0.091)
    rows = {r["system_name"]: r for r in repo.get_squadron_presence(EUW)}
    assert rows["Ekono"]["first_seen"] == "2026-10-06" and rows["Ekono"]["last_seen"] == "2026-10-07"
    assert round(rows["Ekono"]["influence"], 4) == 0.6789
    assert "Expansion" in rows["Ekono"]["recovering_states"]
    assert rows["YF-W"]["first_seen"] == "2026-10-07"
    assert repo.get_squadron_presence("Nobody") == []


def test_cube_systems_with_population(tmp_path):
    repo = _repo(tmp_path)
    for name, xyz in (("In", (10.0, 0.0, 0.0)), ("Corner", (19.0, 19.0, 19.0)), ("Out", (25.0, 0.0, 0.0))):
        repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", (name, *xyz))
    repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                    "VALUES (11, 'In', 5000)")
    got = {r["system_name"]: r for r in repo.get_cube_systems(0.0, 0.0, 0.0, 20.0)}
    assert set(got) == {"In", "Corner"}
    assert got["In"]["population"] == 5000 and got["In"]["system_address"] == 11
    assert got["Corner"]["population"] is None


def test_candidate_cache_replaces_per_source(tmp_path):
    repo = _repo(tmp_path)
    rows = [{"system_name": "Arimavante", "system_address": 4756911035114, "distance_ly": 10.9,
             "faction_count": 6, "faction_present": False}]
    repo.save_expansion_candidates(1, rows, "2026-10-08T10:00:00Z")
    repo.save_expansion_candidates(1, rows[:0] + [dict(rows[0], faction_count=7)], "2026-10-09T10:00:00Z")
    repo.save_expansion_candidates(2, rows, "2026-10-08T10:00:00Z")
    got = repo.get_expansion_candidates(1)
    assert len(got) == 1 and got[0]["faction_count"] == 7 and got[0]["fetched_at"] == "2026-10-09T10:00:00Z"
    assert got[0]["faction_present"] is False
    assert len(repo.get_expansion_candidates(2)) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_repo.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'get_squadron_presence'`.

- [ ] **Step 3: Add the table**

In `persistence/database.py`, in the main-DB migration list, directly after the `pp_control_history` CREATE TABLE string, add:

```python
            # Expansion Forecast: EDSM faction counts for the nearest
            # candidate systems of the likely expansion source (a few dozen rows).
            """CREATE TABLE IF NOT EXISTS expansion_candidates (
                source_address  INTEGER NOT NULL,
                system_address  INTEGER,
                system_name     TEXT    NOT NULL,
                distance_ly     REAL,
                faction_count   INTEGER,
                faction_present INTEGER,
                fetched_at      TEXT    NOT NULL,
                PRIMARY KEY (source_address, system_name)
            )""",
```

- [ ] **Step 4: Add the repository methods**

In `persistence/repository.py`, directly before `def get_faction_history(`, add:

```python
    def get_squadron_presence(self, faction: str) -> list[dict]:
        """One row per system the faction has a snapshot for: first and last
        snapshot date plus the latest snapshot's influence and states. A
        system it left keeps its last rows (pruning only runs on a new save
        for that system/faction), so "been there before" survives."""
        rows = self.db.conn.execute(
            """
            WITH g AS (
                SELECT system_address, MIN(snapshot_date) AS first_seen, MAX(snapshot_date) AS last_seen
                FROM faction_snapshots WHERE faction_name = ? GROUP BY system_address
            )
            SELECT g.system_address, s.system_name, g.first_seen, g.last_seen, fs.influence,
                   fs.faction_state, fs.active_states, fs.pending_states, fs.recovering_states
            FROM g
            JOIN faction_snapshots fs ON fs.system_address = g.system_address
                 AND fs.faction_name = ? AND fs.snapshot_date = g.last_seen
            LEFT JOIN systems s ON s.system_address = g.system_address
            """,
            (faction, faction),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cube_systems(self, x: float, y: float, z: float, half: float) -> list[dict]:
        """Systems inside the cube (each axis within `half` ly), with EDDN
        population where known. Slow on the real DB (~4 s): call from a
        worker thread with its own connection."""
        rows = self.db.conn.execute(
            """
            SELECT c.system_name, c.x, c.y, c.z, b.system_address, b.population
            FROM system_coords c
            LEFT JOIN net.system_bgs_status b ON b.system_name = c.system_name
            WHERE c.x BETWEEN ? AND ? AND c.y BETWEEN ? AND ? AND c.z BETWEEN ? AND ?
            """,
            (x - half, x + half, y - half, y + half, z - half, z + half),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_expansion_candidates(self, source_address: int, rows: list[dict], fetched_at: str) -> None:
        """Replaces the cached candidates for one source system."""
        with self.db.deferred_commit():
            self.db.execute("DELETE FROM expansion_candidates WHERE source_address = ?", (source_address,))
            for r in rows:
                self.db.execute(
                    "INSERT OR REPLACE INTO expansion_candidates (source_address, system_address, system_name, "
                    "distance_ly, faction_count, faction_present, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source_address, r.get("system_address"), r["system_name"], r.get("distance_ly"),
                     r.get("faction_count"), 1 if r.get("faction_present") else 0, fetched_at),
                )

    def get_expansion_candidates(self, source_address: int) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT system_name, system_address, distance_ly, faction_count, faction_present, fetched_at "
            "FROM expansion_candidates WHERE source_address = ? ORDER BY distance_ly",
            (source_address,),
        ).fetchall()
        return [dict(r, faction_present=bool(r["faction_present"])) for r in rows]
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_repo.py -q -p no:cacheprovider`
Expected: PASS. Full suite: PASS.

- [ ] **Step 6: Commit**

```bash
git add persistence/database.py persistence/repository.py tests/test_expansion_forecast_repo.py
git commit -m "feat: repository support for the expansion forecast (presence, cube systems, candidate cache)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Forecast tab and lookup worker

**Files:**
- Create: `edc/ui/panels/expansion_forecast_panel.py`
- Modify: `edc/ui/panels/faction_expansion_dialog.py` (`FactionExpansionDialog.__init__`: wrap existing content in tab 1, add the Forecast tab; add `QTabWidget` to the `PyQt6.QtWidgets` import)
- Test: `tests/test_expansion_forecast_panel.py` (create)

**Interfaces:**
- Consumes: Task 1 (`WATCH_THRESHOLD`, `CUBE_LY`, `LOOKUP_COUNT`, `CACHE_MAX_AGE_H`, `is_current`, `watched_systems`, `likely_source`, `rank_candidates`, `detect_new_systems`, `alert_text`, `expansion_endings`); Task 2 (`get_squadron_presence`, `get_cube_systems`, `save_expansion_candidates`, `get_expansion_candidates`); existing `Repository.get_faction_history`, `get_system_coords_for_names`, `get_squadron_faction_name`; `edsm_faction_lookup.fetch_system_factions(name) -> (result | None, error | None)` where `result["factions"]` items use keys `"Name"`, `"Influence"`.
- Produces: `ExpansionForecastPanel(panel)` (QWidget) with `refresh()`; `panel` is the `PlayerFactionPanel` (uses `panel._repo`, `panel._faction_name`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expansion_forecast_panel.py`:

```python
"""Forecast tab: renders watched systems, cached candidates and the last
result without starting a lookup when the cache is fresh."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

EUW = "Elite United Worlds"


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _table_texts(table):
    return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_forecast_tab_renders_from_fresh_cache(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Ekono'), (2, 'Arimavante')")
    repo.save_faction_snapshot(1, {"Name": EUW, "Influence": 0.80}, today, True, f"{today}T12:00:00Z", "edsm")
    # EUW left Arimavante 20 days ago (older than the 14-day "current" window,
    # inside the 30-day pruning window so the test data isn't deleted on save)
    left = (date.today() - timedelta(days=20)).isoformat()
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.30}, left, False, f"{left}T00:00:00Z", "edsm")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo.save_expansion_candidates(1, [
        {"system_name": "Arimavante", "system_address": 2, "distance_ly": 10.9, "faction_count": 6, "faction_present": False},
        {"system_name": "Tucanae Sector YF-W b2-2", "system_address": 3, "distance_ly": 28.2, "faction_count": 4,
         "faction_present": False},
        {"system_name": "Unlooked", "system_address": 4, "distance_ly": 12.0, "faction_count": None,
         "faction_present": False}], now)
    panel = SimpleNamespace(_repo=repo, _faction_name=EUW)
    w = ExpansionForecastPanel(panel)
    w.refresh()
    assert w._thread is None                       # fresh cache -> no lookup started
    assert _table_texts(w._next_table)[0][0] == "Ekono"
    rows = _table_texts(w._target_table)
    # Arimavante: EUW was there before (left) -> tier 2, so YF-W ranks first
    assert [r[2] for r in rows] == ["Tucanae Sector YF-W b2-2", "Arimavante", "Unlooked"]
    assert rows[1][1] == "2" and rows[1][5] == "yes" and rows[2][1] == "not checked"


def test_no_faction_and_no_watched_system(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel
    repo = _repo(tmp_path)
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=None))
    w.refresh()
    assert "No squadron faction known yet" in w._status.text() and w._thread is None
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Low')")
    repo.save_faction_snapshot(1, {"Name": EUW, "Influence": 0.40}, today, True, f"{today}T12:00:00Z", "edsm")
    w = ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name=EUW))
    w.refresh()
    assert "No faction system at 70% or more" in w._target_status.text() and w._thread is None


def test_worker_result_marks_failed_lookups_not_checked(tmp_path, monkeypatch):
    from edc.ui.panels import expansion_forecast_panel as fp
    repo = _repo(tmp_path)
    for name, xyz, pop in (("Near", (1.0, 0.0, 0.0), 100), ("Far", (15.0, 0.0, 0.0), 100),
                           ("Unknown pop", (2.0, 0.0, 0.0), None), ("Empty", (3.0, 0.0, 0.0), 0)):
        repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", (name, *xyz))
        if pop is not None:
            repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                            "VALUES (abs(random()) % 100000, ?, ?)", (name, pop))
    answers = {"Near": ({"system_address": 9, "factions": [{"Name": "A", "Influence": 0.5},
                                                            {"Name": EUW, "Influence": 0.1}]}, None),
               "Far": (None, "blocked")}
    monkeypatch.setattr(fp, "fetch_system_factions", lambda n: answers[n])
    out = []
    worker = fp._ForecastWorker(repo.db.db_path, {"x": 0.0, "y": 0.0, "z": 0.0}, set(), EUW)
    worker.finished.connect(lambda res, err: out.append((res, err)))
    worker.run()
    res, err = out[0]
    assert err is None and res["unknown_population"] == 1 and res["candidates"] == 2
    by = {r["system_name"]: r for r in res["rows"]}
    assert by["Near"]["faction_count"] == 2 and by["Near"]["faction_present"] is True
    assert by["Far"]["faction_count"] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_panel.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'edc.ui.panels.expansion_forecast_panel'`.

- [ ] **Step 3: Create the panel**

Create `edc/ui/panels/expansion_forecast_panel.py`:

```python
# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.
"""Faction Expansion Tracker -> Forecast tab: the squadron faction's systems
near expansion, a ranked shortlist of likely targets for the likely source,
and the last expansion's result. See
docs/superpowers/specs/2026-10-08-expansion-forecast-design.md."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from edc.core.edsm_faction_lookup import fetch_system_factions
from edc.core.expansion_forecast import (
    CACHE_MAX_AGE_H, CUBE_LY, LOOKUP_COUNT, WATCH_THRESHOLD, alert_text, detect_new_systems, is_current,
    likely_source, rank_candidates, watched_systems,
)
from edc.ui.style import HDR_STYLE, PRIMARY_BUTTON_STYLE, TABLE_STYLE, bulk_table_fill

log = logging.getLogger(__name__)

_NOTE = ("Rules are community-researched, not Frontier documentation. A closer system can be skipped if "
         "the faction left it before tracking began.")
_DIM = "color:#888888; font-size:11px; background:transparent; border:none;"


class _ForecastWorker(QObject):
    """Cube query (slow) + EDSM lookups for the nearest candidates, on its
    own DB connection. Emits ({"rows", "candidates", "unknown_population"}, None)
    or (None, error text)."""
    finished = pyqtSignal(object, object)

    def __init__(self, db_path, source: dict, exclude_names: set, faction: str):
        super().__init__()
        self._db_path, self._source, self._exclude, self._faction = db_path, source, exclude_names, faction

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            cube = Repository(db).get_cube_systems(self._source["x"], self._source["y"], self._source["z"], CUBE_LY)
        except Exception as exc:
            log.exception("Expansion forecast cube query failed")
            self.finished.emit(None, str(exc))
            return
        finally:
            db.close()
        sx, sy, sz = self._source["x"], self._source["y"], self._source["z"]
        populated, unknown = [], 0
        for s in cube:
            if s["system_name"] in self._exclude:
                continue
            if s["population"] is None:
                unknown += 1
                continue
            if s["population"] <= 0:
                continue
            dist = ((s["x"] - sx) ** 2 + (s["y"] - sy) ** 2 + (s["z"] - sz) ** 2) ** 0.5
            if dist > 0:
                populated.append({"system_name": s["system_name"], "system_address": s["system_address"],
                                  "distance_ly": dist})
        populated.sort(key=lambda c: c["distance_ly"])
        rows = []
        for c in populated[:LOOKUP_COUNT]:
            result, _err = fetch_system_factions(c["system_name"])
            if not result:
                rows.append({**c, "faction_count": None, "faction_present": False})
                continue
            names = [f.get("Name") for f in result.get("factions") or [] if (f.get("Influence") or 0) > 0]
            rows.append({**c, "system_address": result.get("system_address") or c["system_address"],
                         "faction_count": len(names), "faction_present": self._faction in names})
        self.finished.emit({"rows": rows, "candidates": len(populated), "unknown_population": unknown}, None)


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setStyleSheet(TABLE_STYLE)
    h = t.horizontalHeader()
    for c in range(len(headers)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    h.setStretchLastSection(True)
    return t


def _fill(table, rows):
    table.setRowCount(len(rows))
    with bulk_table_fill(table):
        for i, row in enumerate(rows):
            for c, text in enumerate(row):
                table.setItem(i, c, QTableWidgetItem(text))


class ExpansionForecastPanel(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ForecastWorker] = None
        self._source: Optional[dict] = None
        self._been: set = set()
        self._current: set = set()

        layout = QVBoxLayout(self)
        self._status = QLabel("")
        self._status.setStyleSheet(_DIM)
        layout.addWidget(self._status)

        hdr = QLabel("NEXT TO EXPAND — faction systems at 70% or more")
        hdr.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr)
        self._next_table = _table(["System", "Influence", "Days ≥75%", "State", "Likely source"])
        self._next_table.setMaximumHeight(140)
        layout.addWidget(self._next_table)

        row = QHBoxLayout()
        hdr2 = QLabel("LIKELY TARGETS")
        hdr2.setStyleSheet(HDR_STYLE)
        row.addWidget(hdr2)
        row.addStretch(1)
        self._refresh_btn = QPushButton("Refresh lookups")
        self._refresh_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._refresh_btn.clicked.connect(lambda: self._start_lookup(force=True))
        row.addWidget(self._refresh_btn)
        layout.addLayout(row)
        self._target_status = QLabel("")
        self._target_status.setWordWrap(True)
        self._target_status.setStyleSheet(_DIM)
        layout.addWidget(self._target_status)
        self._target_table = _table(["#", "Tier", "System", "Distance", "Factions", "Faction here before", "Data"])
        self._target_table.cellClicked.connect(self._copy_name)
        layout.addWidget(self._target_table, 1)
        note = QLabel(_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet(_DIM)
        layout.addWidget(note)

        hdr3 = QLabel("LAST RESULT")
        hdr3.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr3)
        self._last_label = QLabel("—")
        self._last_label.setWordWrap(True)
        layout.addWidget(self._last_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _faction(self) -> Optional[str]:
        return self._panel._faction_name or self._panel._repo.get_squadron_faction_name()

    def refresh(self) -> None:
        faction = self._faction()
        if not faction:
            self._status.setText("No squadron faction known yet.")
            _fill(self._next_table, [])
            _fill(self._target_table, [])
            return
        repo, today = self._panel._repo, date.today()
        presence = repo.get_squadron_presence(faction)
        histories = {r["system_address"]: list(reversed(repo.get_faction_history(r["system_address"], faction)))
                     for r in presence if is_current(r, today) and (r.get("influence") or 0) >= WATCH_THRESHOLD}
        watched = watched_systems(presence, histories, today)
        self._source = likely_source(watched)
        self._been = {r["system_name"] for r in presence if not is_current(r, today)}
        self._current = {r["system_name"] for r in presence if is_current(r, today)}
        self._status.setText(f"{faction} — {len(self._current)} current systems")
        src_name = self._source["system_name"] if self._source else None
        _fill(self._next_table, [
            [w["system_name"] or str(w["system_address"]), f"{(w['influence'] or 0) * 100:.1f}%",
             str(w["days_above"]), w["phase"] or "—",
             ("yes" if w["system_name"] == src_name and self._source["eligible"]
              else "not yet (needs a day at 75%)" if w["system_name"] == src_name else "")]
            for w in watched])
        self._render_last_result(repo, faction, today)
        if not self._source:
            self._target_status.setText("No faction system at 70% or more.")
            _fill(self._target_table, [])
            return
        self._render_targets()
        self._start_lookup(force=False)

    def _render_targets(self, extra: str = "") -> None:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        ranked = rank_candidates([dict(c, been_before=c["system_name"] in self._been) for c in cached])
        fetched = cached[0]["fetched_at"][:16].replace("T", " ") if cached else "never"
        _fill(self._target_table, [
            [str(i + 1) if c["tier"] else "", str(c["tier"]) if c["tier"] else "not checked", c["system_name"],
             f"{c['distance_ly']:.1f} ly" if c.get("distance_ly") is not None else "",
             "" if c["faction_count"] is None else str(c["faction_count"]),
             "yes" if c["been_before"] else "unknown", fetched]
            for i, c in enumerate(ranked)])
        self._target_status.setText(
            f"From {self._source['system_name']}: nearest {len(cached)} candidates in the ±20 ly cube "
            f"(EDSM, {fetched} UTC). Tier 1 = fewer than 7 factions, never there; tier 2 = fewer than 7, "
            f"faction was there before; tier 3 = 7 factions (invasion war).{extra}"
            + ("" if any(c["tier"] for c in ranked) or not cached else
               " No eligible system within ±20 ly — the game would search ±30 ly next, or the expansion fails."))

    def _render_last_result(self, repo, faction, today) -> None:
        new = detect_new_systems(repo, faction, today)
        self._last_label.setText(alert_text(faction, new[0]) if new else
                                 "No new faction system in the last 3 days.")

    def _cache_fresh(self) -> bool:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        if not cached:
            return False
        fetched = datetime.fromisoformat(cached[0]["fetched_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - fetched < timedelta(hours=CACHE_MAX_AGE_H)

    def _start_lookup(self, force: bool) -> None:
        if not self._source or (self._thread is not None and self._thread.isRunning()):
            return
        if not force and self._cache_fresh():
            return
        coords = self._panel._repo.get_system_coords_for_names([self._source["system_name"]])
        xyz = coords.get(self._source["system_name"])
        if not xyz:
            self._target_status.setText(f"No coordinates for {self._source['system_name']} yet.")
            return
        self._target_status.setText("Looking up candidates on EDSM…")
        self._worker = _ForecastWorker(self._panel._repo.db.db_path, {"x": xyz[0], "y": xyz[1], "z": xyz[2]},
                                       set(self._current), self._faction())
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_lookup_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_lookup_finished(self, result, error) -> None:
        if not result:
            self._target_status.setText(f"Lookup failed ({error}) — showing the last cached data.")
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self._panel._repo.save_expansion_candidates(self._source["system_address"], result["rows"], now)
        except Exception:
            log.exception("Failed to save expansion candidates")
        skipped = result["unknown_population"]
        self._render_targets(f" Skipped {skipped} systems with unknown population." if skipped else "")

    def _copy_name(self, row: int, _col: int) -> None:
        item = self._target_table.item(row, 2)
        if item:
            QApplication.clipboard().setText(item.text())
```

- [ ] **Step 4: Add the tab to the Faction Expansion Tracker**

In `edc/ui/panels/faction_expansion_dialog.py`:

1. Add `QTabWidget` to the `from PyQt6.QtWidgets import (...)` list.
2. Add `from edc.ui.panels.expansion_forecast_panel import ExpansionForecastPanel` after the other `edc.` imports.
3. In `FactionExpansionDialog.__init__`, replace the line `        layout = QVBoxLayout(self)` (the first one, right after `self.resize(760, 640)`) with:

```python
        outer = QVBoxLayout(self)
        self._tabs = QTabWidget()
        outer.addWidget(self._tabs)
        target_page = QWidget()
        layout = QVBoxLayout(target_page)
```

4. Directly after `        layout.addWidget(ref)` (the static reference label, before `self._load_pinned()`), add:

```python
        self._tabs.addTab(target_page, "Target system")
        self._forecast = ExpansionForecastPanel(panel)
        self._tabs.addTab(self._forecast, "Forecast")
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_panel.py -q -p no:cacheprovider`
Expected: PASS. Full suite: PASS.

- [ ] **Step 6: Render check on the real database**

Copy `data/edhelper.db` and `data/network_cache.db` to a temp folder, build `Repository(Database(copy))`, create `ExpansionForecastPanel(SimpleNamespace(_repo=repo, _faction_name="Elite United Worlds"))`, call `refresh()`, wait for the lookup worker to finish (run a `QApplication` event loop with a 60 s `QTimer.singleShot` quit), grab a screenshot with `widget.grab().save(path)`, and look at it: Ekono in "Next to expand" with its real state; a ranked candidate list with EDSM faction counts; "Last result" naming Tucanae Sector YF-W b2-2 if run within 3 days of 2026-10-07, otherwise "No new faction system in the last 3 days."

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/expansion_forecast_panel.py edc/ui/panels/faction_expansion_dialog.py tests/test_expansion_forecast_panel.py
git commit -m "feat: Forecast tab in the Faction Expansion Tracker (next to expand, likely targets, last result)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: New-system alert on the Overview and in the Session report

**Files:**
- Modify: `edc/ui/panels/overview_panel.py` (add `new_system_badge` after `squadron_faction_badge`; add `set_new_system_alert`)
- Modify: `edc/ui/main_window.py` (add `_refresh_new_system_alert`; call it from `_notify_bgs_activity` and from the post-replay startup step)
- Modify: `edc/ui/panels/session_activity_dialog.py` (add `_new_label` under `_pp_label`; fill it in `refresh`)
- Test: append to `tests/test_expansion_forecast_panel.py`

**Interfaces:**
- Consumes: Task 1 `detect_new_systems(repo, faction, today)`, `alert_text(faction, item)`; Task 2 `get_squadron_presence`.
- Produces: `OverviewPanel.set_new_system_alert(text: str) -> None`; `MainWindow._refresh_new_system_alert() -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_expansion_forecast_panel.py`:

```python
def test_overview_alert_label():
    QApplication.instance() or QApplication([])
    from edc.ui.panels.overview_panel import OverviewPanel
    ov = OverviewPanel()
    ov.set_new_system_alert("🆕 EUW entered <b>X</b> (9.1%)")
    assert ov.new_system_badge.text() == "🆕 EUW entered <b>X</b> (9.1%)" and not ov.new_system_badge.isHidden()
    ov.set_new_system_alert("")
    assert ov.new_system_badge.isHidden()


def test_main_window_alert_uses_detection(tmp_path):
    from edc.ui.main_window import MainWindow
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'Tucanae Sector YF-W b2-2')")
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.091}, today, False, f"{today}T16:59:55Z", "eddn")
    shown = []
    fake = SimpleNamespace(repo=repo, overview_panel=SimpleNamespace(set_new_system_alert=shown.append),
                           player_faction_panel=SimpleNamespace(_faction_name=EUW))
    MainWindow._refresh_new_system_alert(fake)
    assert shown == ["🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%)"]
    fake.player_faction_panel._faction_name = None
    MainWindow._refresh_new_system_alert(fake)
    assert shown[-1] == ""


def test_session_report_shows_new_system_escaped(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    repo = _repo(tmp_path)
    today = date.today().isoformat()
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (2, 'A <i>b</i>')")
    repo.save_faction_snapshot(2, {"Name": EUW, "Influence": 0.05}, today, False, f"{today}T10:00:00Z", "eddn")
    dlg = SessionActivityDialog(SimpleNamespace(_repo=repo, _faction_name=EUW, _latest_known_tick=None))
    dlg.refresh()
    assert "A &lt;i&gt;b&lt;/i&gt;" in dlg._new_label.text() and not dlg._new_label.isHidden()
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_panel.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'OverviewPanel' object has no attribute 'set_new_system_alert'`.

- [ ] **Step 3: Overview label**

In `edc/ui/panels/overview_panel.py`, directly after `        layout.addWidget(self.squadron_faction_badge)` add:

```python
        # ── New faction system alert (Expansion Forecast) ───────────────────
        self.new_system_badge = QLabel("")
        self.new_system_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.new_system_badge.setWordWrap(True)
        self.new_system_badge.setVisible(False)
        self.new_system_badge.setStyleSheet(
            "QLabel { background: #0d2a1a; border: 1px solid #1a5a3a;"
            "border-radius: 6px; padding: 6px 10px; color: #6BCB77; }"
        )
        layout.addWidget(self.new_system_badge)
```

and directly after the `set_bgs_task_hint` method add:

```python
    def set_new_system_alert(self, text: str) -> None:
        """Expansion Forecast's new-system line (plain text; empty hides it)."""
        self.new_system_badge.setText(text)
        self.new_system_badge.setVisible(bool(text))
```

- [ ] **Step 4: Main window refresh**

In `edc/ui/main_window.py`:

1. Add `from edc.core.expansion_forecast import alert_text, detect_new_systems` next to the other `edc.core` imports.
2. Directly after the `_refresh_bgs_task_hint` method add:

```python
    def _refresh_new_system_alert(self) -> None:
        """Overview line when the squadron faction appeared in a new system
        in the last 3 days (Expansion Forecast spec, section 4)."""
        text = ""
        faction = getattr(self.player_faction_panel, "_faction_name", None)
        if faction:
            try:
                new = detect_new_systems(self.repo, faction)
                text = alert_text(faction, new[0]) if new else ""
            except Exception:
                log.exception("Failed to check for new faction systems")
        self.overview_panel.set_new_system_alert(text)
```

3. In `_notify_bgs_activity`, after the line `self._refresh_bgs_task_hint()`, add `self._refresh_new_system_alert()`.
4. In the post-replay startup step — the block that runs `self._load_shiplocker_inventory()`, `self._load_backpack_inventory()`, `self._refresh_engineering()`, `self._refresh_bgs_task_hint()` in that order — add `self._refresh_new_system_alert()` directly after that `self._refresh_bgs_task_hint()`. (Not in `load_last_system_data`: `tests/test_load_last_system_data_canonn.py` calls it with a minimal fake `self`.)

- [ ] **Step 5: Session report line**

In `edc/ui/panels/session_activity_dialog.py`:

1. Change the import `from edc.core.bgs_tasks import CP_NOTE, cp_text, powerplay_week_start, pp_watch, undermining_alerts` by adding a new line after it: `from edc.core.expansion_forecast import alert_text, detect_new_systems`.
2. Directly after `        layout.addWidget(self._pp_label)` add:

```python
        self._new_label = QLabel("")
        self._new_label.setTextFormat(Qt.TextFormat.RichText)
        self._new_label.setWordWrap(True)
        self._new_label.setStyleSheet("background:transparent; border:none; color:#6BCB77; font-size:12px;")
        self._new_label.setVisible(False)
        layout.addWidget(self._new_label)
```

3. In `refresh`, directly after `        self._render_pp_totals(since)`, add:

```python
        faction = getattr(self._panel, "_faction_name", None)
        try:
            new = detect_new_systems(self._panel._repo, faction) if faction else []
        except Exception:
            log.exception("Failed to check for new faction systems")
            new = []
        self._new_label.setText("<br>".join(html.escape(alert_text(faction, n)) for n in new))
        self._new_label.setVisible(bool(new))
```

- [ ] **Step 6: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_expansion_forecast_panel.py -q -p no:cacheprovider`
Expected: PASS. Full suite: PASS.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/overview_panel.py edc/ui/main_window.py edc/ui/panels/session_activity_dialog.py tests/test_expansion_forecast_panel.py
git commit -m "feat: new faction system alert on the Overview and in the Session report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md` (the "Player Faction (BGS)" bullet)
- Modify: `ARCHITECTURE.md` (`edc/core` module list, `edc/ui/panels` list, database tables)

- [ ] **Step 1: README**

In `README.md`, in the "Player Faction (BGS)" bullet, after the sentence about the Faction Expansion Tracker (ending `mission tally)`), insert:

```
 — with a Forecast tab showing which of your faction's systems is next to expand, a ranked shortlist of likely target systems (looked up on EDSM, using the community-researched expansion rules), and where the last expansion landed; a new-system alert on the Overview and in the Session report flags the faction appearing somewhere new
```

- [ ] **Step 2: ARCHITECTURE**

In `ARCHITECTURE.md`:
- In the `edc/core` list, after the `bgs_tasks.py` entry add: ``- `expansion_forecast.py` — Expansion Forecast rules: watched systems (≥70%), likely source (≥75% for a day), ±20 ly cube, tier ranking (fewer than 7 factions / faction there before / 7 factions), new-system detection (first seen within 3 days, ≤20%), and the expansion-ending detection shared with the Faction Expansion Tracker``
- In the `edc/ui/panels` list, after `faction_expansion_dialog.py` add: ``- `expansion_forecast_panel.py` — Faction Expansion Tracker's Forecast tab; `_ForecastWorker` runs the cube query and EDSM lookups on its own DB connection``
- In the database tables table, after `pp_control_history` add: ``| `expansion_candidates` | EDSM faction counts for the nearest 10 candidate systems of the likely expansion source, refreshed at most once a day |``

- [ ] **Step 3: Commit**

```bash
git add README.md ARCHITECTURE.md
git commit -m "docs: Expansion Forecast in README and ARCHITECTURE

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done criteria

- Full suite green.
- In the running app (project rule — confirmation means seeing it live): Faction Expansion Tracker → Forecast tab shows Ekono and a ranked list for Elite United Worlds; "Refresh lookups" fetches; the Overview and Session report show the new-system line when a new system appears.
