# Colonisation Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface which nearby systems are actually eligible for colonization (genuinely unpopulated, within 15 ly of a populated system) — a passive list centered on the player's current system, plus an on-demand check for a manually-named candidate — on the Squadron tab, next to the existing colonisation construction tracking.

**Architecture:** A new EDSM-backed lookup module (`edc/core/colonisation_eligibility.py`) using the same `sphere-systems` endpoint for both the passive list and the manual check (verified live: the center system itself is always included in the response at `distance: 0`, and an empty `"information": {}` object is EDSM's own signal for "no known population"). A background `QThread` worker in `main_window.py` (mirroring the existing `_BgsTickCheckWorker`/`_CanonnRefreshWorker` pattern) fetches the passive list only when the player's system actually changes, never on every HUD tick. `squadron_panel.py` gets a new card rendering the cached list plus a manual-check row that queries synchronously off a one-shot worker on button click.

**Tech Stack:** Python, PyQt6, `requests` (already a dependency).

## Global Constraints

- EDSM's `sphere-systems` endpoint: `GET https://www.edsm.net/api-v1/sphere-systems?systemName={name}&radius={radius}&showInformation=1`. Verified live, not assumed: the response is a JSON array of `{"distance": float, "bodyCount": int, "name": str, "information": {...} | {}}`. The queried center system is always present in the results at `"distance": 0`. A populated system's `"information"` is a full object (`population`, `allegiance`, `government`, `faction`, `factionState`, `security`, `economy`, `secondEconomy`, `reserve`); a genuinely unpopulated system's `"information"` is an empty object `{}` — this is EDSM's own unpopulated signal, confirmed against real data (e.g. a system 98.53 ly from Sol returning `"information":{}`).
- EDSM's User-Agent-blocking issue was already fixed earlier this session (`edc/core/edsm_faction_lookup.py`'s `_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"`) — reuse the identical header string for every request from the new module, do not omit it or invent a different one.
- This module does NOT share `edsm_faction_lookup.py`'s aggressive shared rate-limit gate (confirmed: `edsm_powerplay.py` doesn't share it either — each EDSM-calling module in this codebase manages its own call frequency appropriate to its own usage pattern). This module's call frequency is inherently low (once per real system change, not per HUD tick), so a lightweight single-request timeout with no retry loop is sufficient — do not port in `edsm_faction_lookup.py`'s full retry/backoff/shared-lock machinery, that would be over-engineering for this call pattern.
- The passive candidates list is fetched via a background `QThread` worker, never on the main thread — this project has a hard, established rule against blocking network calls on the UI thread, reinforced multiple times this session.
- The passive list only refetches when the player's current system actually changes (an in-memory cache in `MainWindow`, keyed by system name, checked before dispatching a new background fetch) — this is the throttle; it is not optional, this project already had one real EDSM rate-limit outage this session from an unthrottled call pattern.
- The manual "Check a system" action is a genuine one-off user click, not a per-refresh poll — it does not need the same throttle, but must still run on a background thread (same `QThread` pattern), and must not be blocked by an in-flight passive-list fetch or vice versa (two independent worker/thread pairs).
- No new database table — this is inherently "what's near me right now" data, not persisted, matching how other current-location-relative lookups in this codebase (e.g. engineer-distance tables) already work.
- `SquadronPanel.__init__` already receives `self._repo` — this feature does NOT need repository access (no local DB table), only the new EDSM module and data handed to it from `main_window.py` after a background fetch completes.

---

## File Structure

- **Create:** `edc/core/colonisation_eligibility.py` — `find_nearby_colonisation_candidates()`, `check_system_eligibility()`.
- **Test:** `tests/test_colonisation_eligibility.py` — new file, mocked EDSM response fixtures (no live network call in the automated suite).
- **Modify:** `edc/ui/main_window.py` — two new one-shot `QThread` worker classes, throttled dispatch on system change, wiring into `squadron_panel`.
- **Modify:** `edc/ui/panels/squadron_panel.py` — new card (passive list + manual-check row), new public methods for `main_window.py` to push results into.

---

### Task 1: EDSM eligibility lookup module

**Files:**
- Create: `edc/core/colonisation_eligibility.py`
- Test: `tests/test_colonisation_eligibility.py`

**Interfaces:**
- Consumes: nothing new (uses `requests`, already a project dependency)
- Produces: `find_nearby_colonisation_candidates(system_name: str, radius_ly: float = 15.0) -> list[dict]` (each dict: `{"name": str, "distance_ly": float}`, closest first, capped at 20, excludes the queried system itself); `check_system_eligibility(system_name: str) -> dict` (`{"eligible": Optional[bool], "reason": str, "nearest_populated_ly": Optional[float]}` — `eligible=None` signals a lookup failure/system-not-found, distinct from a real `False`) — Task 2 calls both by exact name/shape

- [ ] **Step 1: Write the failing tests**

Create `tests/test_colonisation_eligibility.py`:

```python
"""Tests for edc.core.colonisation_eligibility -- EDSM sphere-systems
response parsing, mocked (no live network call in the automated suite).
Real endpoint shape verified live during development: the queried center
system is always present at distance 0; an empty "information": {} object
is EDSM's own signal for "no known population"."""
from unittest.mock import patch

from edc.core.colonisation_eligibility import (
    find_nearby_colonisation_candidates,
    check_system_eligibility,
)


def _sphere_response(entries):
    """entries: list of (name, distance, populated: bool)."""
    out = []
    for name, distance, populated in entries:
        info = {"population": 1000, "allegiance": "Independent"} if populated else {}
        out.append({"distance": distance, "bodyCount": 5, "name": name, "information": info})
    return out


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_find_nearby_excludes_self_and_populated(mocker=None):
    payload = _sphere_response([
        ("Sol", 0, True),
        ("Empty One", 5.0, False),
        ("Populated Neighbor", 3.0, True),
        ("Empty Two", 10.0, False),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol", radius_ly=15.0)
    names = [r["name"] for r in result]
    assert "Sol" not in names
    assert "Populated Neighbor" not in names
    assert names == ["Empty One", "Empty Two"]  # closest first


def test_find_nearby_caps_at_20():
    payload = _sphere_response([(f"System {i}", float(i), False) for i in range(1, 26)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol", radius_ly=25.0)
    assert len(result) == 20
    assert result[0]["name"] == "System 1"


def test_find_nearby_empty_result_on_no_candidates():
    payload = _sphere_response([("Sol", 0, True)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol")
    assert result == []


def test_find_nearby_network_failure_returns_empty_list():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = find_nearby_colonisation_candidates("Sol")
    assert result == []


def test_check_eligibility_candidate_already_populated():
    payload = _sphere_response([("Target System", 0, True)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is False
    assert "populated" in result["reason"].lower()


def test_check_eligibility_unpopulated_with_populated_neighbor():
    payload = _sphere_response([
        ("Target System", 0, False),
        ("Nearby Hub", 8.5, True),
        ("Far Hub", 14.0, True),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is True
    assert result["nearest_populated_ly"] == 8.5


def test_check_eligibility_unpopulated_no_populated_neighbor():
    payload = _sphere_response([
        ("Target System", 0, False),
        ("Also Empty", 10.0, False),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is False
    assert result["nearest_populated_ly"] is None


def test_check_eligibility_system_not_found():
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse([])):
        result = check_system_eligibility("Totally Made Up System Name")
    assert result["eligible"] is None
    assert "not found" in result["reason"].lower()


def test_check_eligibility_network_failure():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_colonisation_eligibility.py -v`
Expected: every test FAILs with `ModuleNotFoundError: No module named 'edc.core.colonisation_eligibility'`.

- [ ] **Step 3: Implement the module**

Create `edc/core/colonisation_eligibility.py`:

```python
"""Colonisation eligibility lookups via EDSM's sphere-systems endpoint --
answers "which nearby systems are unpopulated and thus colonisable" and
"is this specific system eligible right now". Advisory only: EDSM's
population data is crowdsourced and can lag real-time changes.

Real game rule (verified, not guessed): a system is colonisable only if
genuinely unpopulated and within 15 ly of an existing populated system,
claimed via a System Colonisation Contact at any starport. A second
mechanic (10 ly chained expansion from your own already-built colony) is
deliberately out of scope for this module -- only the 15 ly
current-location rule is implemented.

EDSM's sphere-systems response always includes the queried center system
itself at "distance": 0. A populated system's "information" is a full
object; a genuinely unpopulated system's "information" is an empty object
{} -- confirmed live against real EDSM data during development (e.g. a
system 98.53 ly from Sol returned "information":{}).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_SPHERE_URL = "https://www.edsm.net/api-v1/sphere-systems"
_TIMEOUT = 15

# EDSM's Cloudflare front-end 403s the default python-requests User-Agent
# specifically -- same fix already applied elsewhere in this codebase (see
# edc/core/edsm_faction_lookup.py's own comment for the confirmation this
# was root-caused, not guessed).
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"

_MAX_CANDIDATES = 20
_DEFAULT_RADIUS_LY = 15.0


def _query_sphere(system_name: str, radius_ly: float) -> Optional[List[Dict[str, Any]]]:
    """Returns the raw sphere-systems JSON array, or None on any failure
    (network error, bad response, non-list payload)."""
    try:
        resp = requests.get(
            _SPHERE_URL,
            params={"systemName": system_name, "radius": radius_ly, "showInformation": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("EDSM sphere-systems lookup failed for %r", system_name)
        return None
    if not isinstance(data, list):
        return None
    return data


def _is_unpopulated(entry: Dict[str, Any]) -> bool:
    info = entry.get("information")
    return isinstance(info, dict) and not info


def find_nearby_colonisation_candidates(system_name: str, radius_ly: float = _DEFAULT_RADIUS_LY) -> List[Dict[str, Any]]:
    """Unpopulated systems within radius_ly of system_name, closest first,
    capped at _MAX_CANDIDATES. Each result: {"name": str, "distance_ly": float}.
    Returns [] on lookup failure or when nothing qualifies -- callers can't
    distinguish "EDSM unreachable" from "genuinely no candidates" from this
    return value alone; that distinction isn't needed for the passive list
    (both render as an empty list either way in the UI)."""
    data = _query_sphere(system_name, radius_ly)
    if data is None:
        return []

    candidates = []
    for entry in data:
        distance = entry.get("distance")
        name = entry.get("name")
        if not isinstance(name, str) or not name or not isinstance(distance, (int, float)):
            continue
        if distance <= 0:
            continue  # the queried system itself
        if not _is_unpopulated(entry):
            continue
        candidates.append({"name": name, "distance_ly": float(distance)})

    candidates.sort(key=lambda c: c["distance_ly"])
    return candidates[:_MAX_CANDIDATES]


def check_system_eligibility(system_name: str) -> Dict[str, Any]:
    """For a manually-named candidate system: is it itself unpopulated,
    and is there a populated system within 15 ly of it (the actual claim
    requirement). Returns {"eligible": Optional[bool], "reason": str,
    "nearest_populated_ly": Optional[float]} -- eligible=None means the
    lookup itself failed or the system wasn't found in EDSM, distinct from
    a real ineligibility verdict."""
    data = _query_sphere(system_name, _DEFAULT_RADIUS_LY)
    if data is None:
        return {"eligible": None, "reason": "Lookup failed -- EDSM unreachable.", "nearest_populated_ly": None}
    if not data:
        return {"eligible": None, "reason": "System not found in EDSM.", "nearest_populated_ly": None}

    target = next((e for e in data if e.get("distance") == 0), None)
    if target is None:
        return {"eligible": None, "reason": "System not found in EDSM.", "nearest_populated_ly": None}

    if not _is_unpopulated(target):
        return {"eligible": False, "reason": "This system is already populated.", "nearest_populated_ly": None}

    nearest_populated_ly = None
    for entry in data:
        distance = entry.get("distance")
        if not isinstance(distance, (int, float)) or distance <= 0:
            continue
        if _is_unpopulated(entry):
            continue
        if nearest_populated_ly is None or distance < nearest_populated_ly:
            nearest_populated_ly = float(distance)

    if nearest_populated_ly is None:
        return {
            "eligible": False,
            "reason": f"Unpopulated, but no populated system within {_DEFAULT_RADIUS_LY:.0f} ly to claim it from.",
            "nearest_populated_ly": None,
        }

    return {
        "eligible": True,
        "reason": f"Unpopulated, {nearest_populated_ly:.1f} ly from the nearest populated system.",
        "nearest_populated_ly": nearest_populated_ly,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_colonisation_eligibility.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all tests pass (87 existing plus the 9 new ones).

- [ ] **Step 6: Live verification (development-time only, not part of the automated suite)**

Run a one-off interpreter check confirming the module reaches the real EDSM endpoint and returns sane data, e.g.:
```
python -c "from edc.core.colonisation_eligibility import find_nearby_colonisation_candidates; print(find_nearby_colonisation_candidates('Sol', 15))"
```
Expected: a list (possibly empty, since Sol's immediate neighborhood is densely populated — try a more remote real system name if Sol returns empty, to confirm the unpopulated-detection logic actually fires on real data, not just the mocked tests).

- [ ] **Step 7: Byte-compile check**

Run: `python -m py_compile edc/core/colonisation_eligibility.py`
Expected: no output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add edc/core/colonisation_eligibility.py tests/test_colonisation_eligibility.py
git commit -m "feat: add EDSM-backed colonisation eligibility lookup"
```

---

### Task 2: Squadron tab UI + background wiring

**Files:**
- Modify: `edc/ui/main_window.py`
- Modify: `edc/ui/panels/squadron_panel.py`

**Interfaces:**
- Consumes: `find_nearby_colonisation_candidates(system_name, radius_ly=15.0) -> list[dict]`, `check_system_eligibility(system_name) -> dict` from Task 1
- Produces: nothing consumed by other tasks — this is the final task

- [ ] **Step 1: Add two background worker classes to `main_window.py`**

Re-read `edc/ui/main_window.py` fresh (flagged frequently-stale by this project's CLAUDE.md). Directly after the existing `_BgsTickCheckWorker` class, add:

```python
class _ColonisationCandidatesWorker(QObject):
    """One-shot background fetch of nearby colonisation candidates -- a
    fresh instance is created only when the player's current system
    actually changes, never on every HUD refresh (see
    _maybe_refresh_colonisation_candidates), matching this project's
    established throttle-then-cache pattern for EDSM calls."""
    finished = pyqtSignal(str, list)  # system_name queried, candidates list

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        from edc.core.colonisation_eligibility import find_nearby_colonisation_candidates
        result = find_nearby_colonisation_candidates(self._system_name)
        self.finished.emit(self._system_name, result)


class _ColonisationEligibilityCheckWorker(QObject):
    """One-shot background check for a manually-named candidate system --
    created only on the user's explicit 'Check' button click, not throttled
    (a genuine one-off action, not a per-refresh poll)."""
    finished = pyqtSignal(dict)

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        from edc.core.colonisation_eligibility import check_system_eligibility
        result = check_system_eligibility(self._system_name)
        self.finished.emit(result)
```

- [ ] **Step 2: Add instance state for both worker/thread pairs**

In `MainWindow.__init__`, directly after the existing `self._bgs_tick_worker: _BgsTickCheckWorker | None = None` line, add:

```python
        self._colonisation_candidates_thread: QThread | None = None
        self._colonisation_candidates_worker: _ColonisationCandidatesWorker | None = None
        self._colonisation_candidates_system: str | None = None  # last system successfully queried for
        self._colonisation_check_thread: QThread | None = None
        self._colonisation_check_worker: _ColonisationEligibilityCheckWorker | None = None
```

- [ ] **Step 3: Dispatch the passive-list worker, throttled on real system change**

Add a new method, placed near `_on_bgs_tick_check_tick()`/`_on_bgs_tick_check_finished()`:

```python
    def _maybe_refresh_colonisation_candidates(self) -> None:
        system_name = getattr(self.state, "system", None)
        if not system_name or system_name == self._colonisation_candidates_system:
            return
        if self._colonisation_candidates_thread and self._colonisation_candidates_thread.isRunning():
            return  # a fetch is already in flight -- next real system change will retry
        self._colonisation_candidates_worker = _ColonisationCandidatesWorker(system_name)
        self._colonisation_candidates_thread = QThread()
        self._colonisation_candidates_worker.moveToThread(self._colonisation_candidates_thread)
        self._colonisation_candidates_thread.started.connect(self._colonisation_candidates_worker.run)
        self._colonisation_candidates_worker.finished.connect(self._on_colonisation_candidates_finished)
        self._colonisation_candidates_worker.finished.connect(self._colonisation_candidates_thread.quit)
        self._colonisation_candidates_thread.start()

    def _on_colonisation_candidates_finished(self, system_name: str, candidates: list) -> None:
        self._colonisation_candidates_system = system_name
        self.squadron_panel.set_colonisation_candidates(system_name, candidates)
```

Note: `self._colonisation_candidates_system` is only updated to `system_name` on actual completion (not on dispatch) -- so if the fetch fails or the module returns `[]` due to a lookup error rather than a genuine empty result, the cache still records this system as "queried" and won't retry until the NEXT system change. This matches the design's stated throttle behavior (cache is keyed by "have we asked about this system since arriving," not by "did the last query succeed") -- a transient EDSM failure is not retried until the next jump, which is an acceptable tradeoff for a low-stakes advisory feature, not a defect to fix in this task.

- [ ] **Step 4: Wire the throttled dispatch into the FSDJump/Location event path**

Find the existing dispatch block (confirmed current as of this plan's own research pass — `main_window.py:1935-1936`, but re-read the file fresh to confirm before editing, this file changes often):
```python
        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots(self.state.factions_timestamp)
```
Directly after it, add a new, narrower block (FSDJump/Location only, matching the design's "on real system arrival" intent -- Docked doesn't change the system, so it's deliberately excluded here even though the faction-snapshot block above includes it for an unrelated reason):

```python
        if name in ("FSDJump", "Location"):
            self._maybe_refresh_colonisation_candidates()
```

- [ ] **Step 5: Add the manual-check dispatch method**

Add directly after `_on_colonisation_candidates_finished()`:

```python
    def _on_check_colonisation_eligibility_clicked(self, system_name: str) -> None:
        if not system_name.strip():
            return
        if self._colonisation_check_thread and self._colonisation_check_thread.isRunning():
            return  # a check is already in flight -- ignore rapid double-clicks
        self._colonisation_check_worker = _ColonisationEligibilityCheckWorker(system_name.strip())
        self._colonisation_check_thread = QThread()
        self._colonisation_check_worker.moveToThread(self._colonisation_check_thread)
        self._colonisation_check_thread.started.connect(self._colonisation_check_worker.run)
        self._colonisation_check_worker.finished.connect(self.squadron_panel.set_eligibility_check_result)
        self._colonisation_check_worker.finished.connect(self._colonisation_check_thread.quit)
        self._colonisation_check_thread.start()
```

- [ ] **Step 6: Connect the Squadron panel's manual-check button to `main_window.py`**

Find where `self.squadron_panel = SquadronPanel(self.repo)` is constructed (re-read fresh to confirm current line). Directly after it, add:

```python
        self.squadron_panel.eligibility_check_requested.connect(self._on_check_colonisation_eligibility_clicked)
```

(This assumes `SquadronPanel` gains a new `eligibility_check_requested = pyqtSignal(str)` signal in Step 7 below, emitted when the user clicks "Check" -- add the `.connect(...)` line here regardless of Step 7's exact ordering, since both files are edited in this same task.)

- [ ] **Step 7: Add the new card to `squadron_panel.py`**

Re-read `edc/ui/panels/squadron_panel.py` fresh. Add `pyqtSignal` to the existing `from PyQt6.QtCore import Qt, pyqtSignal` import if not already present (it already is, per the current file's import line -- confirm, don't duplicate). Add `QLineEdit` to the existing `QtWidgets` import block if not already present (it already is, used by the colonisation depot add-row -- confirm, don't duplicate).

Add a new class-level signal to `SquadronPanel`, alongside any other existing signals (check the class body for an existing signal declaration pattern to match; if none exists, add it as the first line of the class body):

```python
    eligibility_check_requested = pyqtSignal(str)  # system name to check
```

In `SquadronPanel.__init__`, add new instance state directly after `self._depots = []`-style initialization (match whatever the existing colonisation-depot state initialization looks like):

```python
        self._colonisation_candidates: list = []
        self._colonisation_candidates_system: Optional[str] = None
```

Directly after the existing colonisation-construction card block (ends with `root.addWidget(colon_card)`), add a new card:

```python
        # ── Colonisation candidates — nearby unpopulated systems ────────────
        cand_card = QFrame()
        cand_card.setStyleSheet(_CARD_STYLE)
        cand_l = QVBoxLayout(cand_card)
        cand_l.setContentsMargins(8, 6, 8, 6)
        cand_l.setSpacing(4)

        cand_hdr = QLabel("COLONISATION CANDIDATES — WITHIN 15 LY")
        cand_hdr.setStyleSheet(_HDR_STYLE)
        cand_l.addWidget(cand_hdr)

        self._candidates_status_label = QLabel("")
        self._candidates_status_label.setWordWrap(True)
        self._candidates_status_label.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        cand_l.addWidget(self._candidates_status_label)

        self._candidates_table = QTableWidget()
        self._candidates_table.setColumnCount(2)
        self._candidates_table.setHorizontalHeaderLabels(["System", "Dist (ly)"])
        self._candidates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._candidates_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._candidates_table.verticalHeader().setVisible(False)
        self._candidates_table.setAlternatingRowColors(True)
        self._candidates_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        cch = self._candidates_table.horizontalHeader()
        cch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cch.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._candidates_table.setMaximumHeight(160)
        cand_l.addWidget(self._candidates_table)

        check_row = QHBoxLayout()
        self._check_system_edit = QLineEdit()
        self._check_system_edit.setPlaceholderText("Check a specific system name")
        self._check_system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        check_btn = QPushButton("Check")
        check_btn.setStyleSheet(_BTN_STYLE)
        check_btn.clicked.connect(self._on_check_clicked)
        check_row.addWidget(self._check_system_edit, 1)
        check_row.addWidget(check_btn)
        cand_l.addLayout(check_row)

        self._check_result_label = QLabel("")
        self._check_result_label.setWordWrap(True)
        self._check_result_label.setStyleSheet("background:transparent; border:none;")
        cand_l.addWidget(self._check_result_label)

        cand_caveat = QLabel(
            "Advisory only — based on EDSM's crowdsourced population data, which can lag "
            "real-time changes. Confirms what's in range, not that you're currently at a "
            "valid Colonisation Contact."
        )
        cand_caveat.setWordWrap(True)
        cand_caveat.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        cand_l.addWidget(cand_caveat)

        root.addWidget(cand_card)
```

(Placed directly after `root.addWidget(colon_card)` and before the `# ── Rank history ──` section -- re-read the file fresh to confirm this is still the correct insertion point.)

- [ ] **Step 8: Add the new methods to `SquadronPanel`**

Add directly after the existing `_on_depot_cell_clicked()` method (or wherever the colonisation-depot section's methods end):

```python
    # ── Colonisation candidates ─────────────────────────────────────────

    def set_colonisation_candidates(self, system_name: str, candidates: list) -> None:
        self._colonisation_candidates = candidates
        self._colonisation_candidates_system = system_name

        self._candidates_table.setRowCount(len(candidates))
        for row, c in enumerate(candidates):
            name_item = QTableWidgetItem(c.get("name") or "—")
            dist_item = QTableWidgetItem(f"{c.get('distance_ly', 0):.1f}")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._candidates_table.setItem(row, 0, name_item)
            self._candidates_table.setItem(row, 1, dist_item)

        if candidates:
            self._candidates_status_label.setText(f"Near {system_name}:")
        else:
            self._candidates_status_label.setText(
                f"No unpopulated systems found within 15 ly of {system_name}."
            )

    def _on_check_clicked(self) -> None:
        system_name = self._check_system_edit.text().strip()
        if not system_name:
            return
        self._check_result_label.setText("Checking…")
        self._check_result_label.setStyleSheet("color:#888888; background:transparent; border:none;")
        self.eligibility_check_requested.emit(system_name)

    def set_eligibility_check_result(self, result: dict) -> None:
        eligible = result.get("eligible")
        reason = result.get("reason") or ""
        if eligible is True:
            color = "#6BCB77"
            prefix = "✓ Eligible — "
        elif eligible is False:
            color = "#FF6B6B"
            prefix = "✗ Not eligible — "
        else:
            color = "#FFB347"
            prefix = "⚠ "
        self._check_result_label.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        self._check_result_label.setText(f"{prefix}{reason}")
```

- [ ] **Step 9: Byte-compile check**

Run: `python -m py_compile edc/ui/main_window.py edc/ui/panels/squadron_panel.py`
Expected: no output, exit code 0.

- [ ] **Step 10: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all tests still pass (this task adds no new automated tests — UI wiring is verified visually per this project's convention).

- [ ] **Step 11: Visual + live verification**

Launch the app (or a headless `QT_QPA_PLATFORM=offscreen` smoke check if a full launch isn't available), open the Squadron tab:
- Confirm the new "COLONISATION CANDIDATES — WITHIN 15 LY" card renders below the existing "COLONISATION CONSTRUCTION — TRACKED SITES" card, with the empty-state message showing before any jump has happened this session.
- If a live journal/game session is available: jump to a new system, confirm the passive list populates (or shows the correct empty-state message) shortly after arrival, without any noticeable UI freeze during the fetch (the whole point of the background-thread requirement).
- Type a known-populated system name (e.g. "Sol") into the manual-check box and click Check — confirm it reports "Not eligible — already populated."
- Type a genuinely remote/fictional system name and confirm the "not found" path renders sensibly rather than crashing.
- Jump again to a different real system and confirm the passive list re-fetches for the new system (not stuck showing the previous system's candidates).

- [ ] **Step 12: Commit**

```bash
git add edc/ui/main_window.py edc/ui/panels/squadron_panel.py
git commit -m "feat: add Colonisation Candidates card to Squadron tab"
```
