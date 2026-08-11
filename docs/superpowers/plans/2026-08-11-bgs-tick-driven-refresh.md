# BGS Tick-Driven Refresh + Overview HUD Flash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trigger the Player Faction tab's full EDSM refresh off the actual detected BGS tick time (via `tick.edcd.io`) instead of a calendar-day approximation, and flash a brief "tick detected, updating" notice on the Overview HUD when that happens.

**Architecture:** A new pure-function client polls `tick.edcd.io` from a background thread every 10 minutes. A new pure decision function (independently testable, no Qt dependency) decides whether a detected tick is new enough to warrant a refresh. The existing calendar-day refresh trigger (`_maybe_auto_refresh_all()`) stays completely unmodified as the fallback for whenever the tick service is unreachable. Everything funnels into the existing, already-working `_start_refresh_all()` worker.

**Tech Stack:** Python, `requests` (already a dependency), PyQt6 (`QTimer`, `QObject`/`QThread` worker pattern, `QGraphicsOpacityEffect`/`QPropertyAnimation`), pytest.

## Global Constraints

- No new dependencies — `requests` already used identically elsewhere in this codebase (`edc/core/edsm_faction_lookup.py`, `edc/core/eddn_publisher.py`).
- User-Agent on the new HTTP call: `"EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"` — same identifying string used by every other outbound HTTP call added this session.
- `tick.edcd.io`'s `/api/tick` endpoint returns a bare JSON string (confirmed live, e.g. `"2026-08-11T10:51:03+00:00"`) — `response.json()` parses it directly to a Python `str`. No auth, no documented rate limit.
- The existing calendar-day fallback path (`player_faction_panel.py::_maybe_auto_refresh_all()`) must not be modified at all — it remains the safety net when the tick fetch fails.
- No "next tick" prediction anywhere — the service has no forecast endpoint, and inventing one from historical data was explicitly rejected during design (a guess presented as fact).
- Polling only, no WebSocket — deliberate choice made during design to avoid a second long-lived external connection with the same failure class already found and fixed today in `eddn_listener.py`.

---

### Task 1: `bgs_tick.py` — tick-fetching client

**Files:**
- Create: `edc/core/bgs_tick.py`
- Test: `tests/test_bgs_tick.py`

**Interfaces:**
- Produces: `fetch_latest_tick() -> Optional[str]` — returns the ISO8601 UTC timestamp string of the most recently detected BGS tick, or `None` on any failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bgs_tick.py`:

```python
"""Tests for fetch_latest_tick() -- mocked HTTP only, no live network call."""
from unittest.mock import Mock, patch

from edc.core.bgs_tick import fetch_latest_tick


def _fake_response(status_code=200, json_value="2026-08-11T10:51:03+00:00"):
    resp = Mock()
    resp.status_code = status_code
    if status_code == 200:
        resp.raise_for_status = Mock()
    else:
        resp.raise_for_status = Mock(side_effect=Exception(f"status {status_code}"))
    resp.json = Mock(return_value=json_value)
    return resp


def test_fetch_latest_tick_returns_string_on_success():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response()):
        result = fetch_latest_tick()
    assert result == "2026-08-11T10:51:03+00:00"


def test_fetch_latest_tick_returns_none_on_non_200():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response(status_code=500)):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_malformed_body():
    with patch(
        "edc.core.bgs_tick.requests.get",
        return_value=_fake_response(json_value={"not": "a string"}),
    ):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_empty_string():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response(json_value="")):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_network_error():
    with patch("edc.core.bgs_tick.requests.get", side_effect=Exception("connection refused")):
        result = fetch_latest_tick()
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bgs_tick.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'edc.core.bgs_tick'`

- [ ] **Step 3: Implement `bgs_tick.py`**

Create `edc/core/bgs_tick.py`:

```python
"""BGS tick detection via tick.edcd.io -- a free public community service
that detects and timestamps the game's actual daily BGS tick (faction
state recalculation), instead of approximating it via a calendar-day
boundary. Confirmed live: GET /api/tick returns a bare JSON string like
"2026-08-11T10:51:03+00:00", no auth, no documented rate limit.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

_TICK_URL = "https://tick.edcd.io/api/tick"
_TIMEOUT = 10
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


def fetch_latest_tick() -> Optional[str]:
    """
    Returns the most recently detected BGS tick as an ISO8601 UTC
    timestamp string, or None on any failure -- network error, timeout,
    bad/unexpected response shape. Call from a worker thread only, never
    the UI thread.
    """
    try:
        resp = requests.get(_TICK_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Failed to fetch latest BGS tick: %s", exc)
        return None
    if not isinstance(data, str) or not data:
        return None
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bgs_tick.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add edc/core/bgs_tick.py tests/test_bgs_tick.py
git commit -m "feat: add tick.edcd.io client for real BGS tick detection"
```

---

### Task 2: `FactionRefreshTracker` — persist the last-handled tick

**Files:**
- Modify: `edc/core/faction_refresh_tracker.py`
- Test: `tests/test_faction_refresh_tracker.py`

**Interfaces:**
- Produces: `FactionRefreshTracker.last_refreshed_tick() -> Optional[str]`, `FactionRefreshTracker.mark_refreshed_tick(tick_iso: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_refresh_tracker.py`:

```python
"""Tests for FactionRefreshTracker's tick-tracking methods."""
import json

from edc.core.faction_refresh_tracker import FactionRefreshTracker


def test_last_refreshed_tick_is_none_before_anything_is_marked(tmp_path):
    tracker = FactionRefreshTracker(tmp_path / "faction_refresh.json")
    assert tracker.last_refreshed_tick() is None


def test_mark_and_read_back_refreshed_tick(tmp_path):
    tracker = FactionRefreshTracker(tmp_path / "faction_refresh.json")
    tracker.mark_refreshed_tick("2026-08-11T10:51:03+00:00")
    assert tracker.last_refreshed_tick() == "2026-08-11T10:51:03+00:00"


def test_marking_refreshed_tick_does_not_clobber_existing_keys(tmp_path):
    path = tmp_path / "faction_refresh.json"
    tracker = FactionRefreshTracker(path)
    tracker.mark_refreshed()
    tracker.mark_csv_imported()

    tracker.mark_refreshed_tick("2026-08-11T10:51:03+00:00")

    assert tracker.last_refresh() is not None
    assert tracker.last_csv_import() is not None
    assert tracker.last_refreshed_tick() == "2026-08-11T10:51:03+00:00"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"last_refresh", "last_csv_import", "last_refreshed_tick"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_faction_refresh_tracker.py -v`
Expected: FAIL with `AttributeError: 'FactionRefreshTracker' object has no attribute 'last_refreshed_tick'`

- [ ] **Step 3: Implement the two new methods**

In `edc/core/faction_refresh_tracker.py`, add after the existing `mark_csv_imported()` method (end of the class):

```python
    def last_refreshed_tick(self) -> Optional[str]:
        val = self._read().get("last_refreshed_tick")
        return val if isinstance(val, str) and val else None

    def mark_refreshed_tick(self, tick_iso: str) -> None:
        try:
            data = self._read()
            data["last_refreshed_tick"] = tick_iso
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            log.exception("Failed to save last_refreshed_tick")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_faction_refresh_tracker.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add edc/core/faction_refresh_tracker.py tests/test_faction_refresh_tracker.py
git commit -m "feat: FactionRefreshTracker tracks the last BGS tick refreshed against"
```

---

### Task 3: `player_faction_panel.py` — tick-driven refresh trigger

**Files:**
- Modify: `edc/ui/panels/player_faction_panel.py`
- Test: `tests/test_player_faction_tick_decision.py`

**Interfaces:**
- Consumes: `fetch_latest_tick()` return shape (`Optional[str]`) from Task 1; `FactionRefreshTracker.last_refreshed_tick()`/`mark_refreshed_tick()` from Task 2.
- Produces: module-level `_should_start_tick_refresh(tick_iso, last_refreshed_tick, faction_name, refresh_already_running) -> bool` (pure, no Qt dependency — this is what Task 4's controller code and this task's own tests both rely on being correct). `PlayerFactionPanel.maybe_refresh_for_tick(tick_iso: Optional[str]) -> None` (instance method, called by Task 4's timer). `PlayerFactionPanel.tick_refresh_started` (new `pyqtSignal()`, connected by Task 5's HUD flash).

This task deliberately separates the **decision** (pure function, fully unit-testable) from the **side effects** (starting the QThread-based refresh worker, which needs a real `QApplication` to construct `PlayerFactionPanel` and isn't unit-tested here — consistent with this file having zero existing unit tests today, verified live instead, same as every other panel in this codebase).

- [ ] **Step 1: Write the failing test for the pure decision function**

Create `tests/test_player_faction_tick_decision.py`:

```python
"""Tests for _should_start_tick_refresh() -- the pure decision logic
behind PlayerFactionPanel.maybe_refresh_for_tick(). Deliberately has no
Qt/QApplication dependency so it can be tested directly."""
from edc.ui.panels.player_faction_panel import _should_start_tick_refresh


def test_starts_refresh_on_genuinely_new_tick():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick="2026-08-10T09:12:44+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is True


def test_does_not_start_when_tick_is_none():
    assert _should_start_tick_refresh(
        tick_iso=None,
        last_refreshed_tick="2026-08-10T09:12:44+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_tick_already_handled():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick="2026-08-11T10:51:03+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_no_faction_known():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name=None,
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_refresh_already_running():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name="Some Faction",
        refresh_already_running=True,
    ) is False


def test_starts_refresh_on_first_ever_tick_seen():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_player_faction_tick_decision.py -v`
Expected: FAIL with `ImportError: cannot import name '_should_start_tick_refresh'`

- [ ] **Step 3: Implement the pure decision function**

In `edc/ui/panels/player_faction_panel.py`, add directly after the existing `_in_weekly_maintenance_window()` function (around line 39, before `_CARD_STYLE = ...`):

```python
def _should_start_tick_refresh(
    tick_iso: Optional[str],
    last_refreshed_tick: Optional[str],
    faction_name: Optional[str],
    refresh_already_running: bool,
) -> bool:
    """Pure decision logic for whether a detected BGS tick warrants
    starting a full refresh -- kept free of Qt/self so it's directly
    unit-testable. tick_iso is None whenever fetch_latest_tick() failed
    this round; the existing calendar-day path remains the fallback for
    that case, so this simply does nothing rather than trying to guess."""
    if tick_iso is None or not faction_name or refresh_already_running:
        return False
    return tick_iso != last_refreshed_tick
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_player_faction_tick_decision.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Wire the pure function into the panel**

In `edc/ui/panels/player_faction_panel.py`:

Add the new signal as a class attribute on `PlayerFactionPanel`, directly after the class docstring (around line 494, right before `def __init__`):

```python
    tick_refresh_started = pyqtSignal()
```

In `__init__`, add a new instance attribute directly after `self._auto_refresh_checked: bool = False` (around line 509):

```python
        self._pending_tick: Optional[str] = None
```

Add the new public method directly after `_start_refresh_all()` (which ends around line 1755, right before `def _on_cancel_refresh_clicked`):

```python
    def maybe_refresh_for_tick(self, tick_iso: Optional[str]) -> None:
        """Called periodically from MainWindow with the latest result of
        fetch_latest_tick() (None if that fetch failed this round -- the
        existing calendar-day startup check, _maybe_auto_refresh_all(),
        remains the fallback for that case, unmodified)."""
        refresh_running = bool(self._refresh_all_thread and self._refresh_all_thread.isRunning())
        last_tick = self._refresh_tracker.last_refreshed_tick() if self._refresh_tracker else None
        if not _should_start_tick_refresh(tick_iso, last_tick, self._faction_name, refresh_running):
            return
        self._pending_tick = tick_iso
        self.tick_refresh_started.emit()
        self._start_refresh_all()
```

Modify `_on_refresh_all_finished()` (around line 1765-1771) to also mark the pending tick as handled once the refresh genuinely completes -- mirrors the existing `mark_refreshed()` call immediately below it, so an interrupted refresh (app closed mid-way) never marks the tick as handled, same as the calendar-day path already relies on:

```python
    def _on_refresh_all_finished(self, refreshed: int, failed: int, retreated: int = 0):
        self._refresh_all_btn.setEnabled(True)
        self._cancel_refresh_btn.setVisible(False)
        self._cancel_refresh_btn.setEnabled(True)

        if self._refresh_tracker:
            self._refresh_tracker.mark_refreshed()
            if self._pending_tick:
                self._refresh_tracker.mark_refreshed_tick(self._pending_tick)
        self._pending_tick = None
```

(This replaces the original 3-line block that ended at `self._refresh_tracker.mark_refreshed()` -- everything else in `_on_refresh_all_finished()` below that point, starting with `failed_txt = ...`, is unchanged.)

- [ ] **Step 6: Compile-check**

Run: `python -m py_compile edc/ui/panels/player_faction_panel.py`
Expected: no output (success)

- [ ] **Step 7: Run the full test file once more to confirm nothing broke**

Run: `python -m pytest tests/test_player_faction_tick_decision.py -v`
Expected: PASS (6 passed)

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/player_faction_panel.py tests/test_player_faction_tick_decision.py
git commit -m "feat: PlayerFactionPanel triggers refresh on a genuinely new BGS tick"
```

---

### Task 4: `main_window.py` — periodic tick-check timer

**Files:**
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `edc.core.bgs_tick.fetch_latest_tick() -> Optional[str]` (Task 1); `self.player_faction_panel.maybe_refresh_for_tick(tick_iso: Optional[str]) -> None` (Task 3).
- Produces: nothing new for later tasks to consume (Task 5 connects to the panel's signal directly, not to anything here).

No automated test for this task -- consistent with this file's existing convention (zero unit tests touch `main_window.py` anywhere in this codebase; verified live instead). Compile-check plus live verification are this task's checks.

- [ ] **Step 1: Add the import**

In `edc/ui/main_window.py`, find the existing line `from edc.core.faction_refresh_tracker import FactionRefreshTracker` (around line 68) and add a new import line directly after it:

```python
from edc.core.bgs_tick import fetch_latest_tick
```

- [ ] **Step 2: Add the worker class**

Add this class directly after `_EddnFlushWorker` (which ends around line 305, right before `class _CanonnRefreshWorker`):

```python
class _BgsTickCheckWorker(QObject):
    """One-shot background check against tick.edcd.io -- a fresh instance
    is created per QTimer firing (see _on_bgs_tick_check_tick), same
    pattern as _EddnFlushWorker / _on_market_flush_tick."""
    finished = pyqtSignal(object)  # Optional[str]

    def run(self):
        result = fetch_latest_tick()
        self.finished.emit(result)
```

- [ ] **Step 3: Add the QTimer**

In `edc/ui/main_window.py`, find the existing `self._player_faction_refresh_timer` setup block (around line 892-899) and add the new timer directly after it:

```python
        self._bgs_tick_timer = QTimer(self)
        # tick.edcd.io detects real BGS ticks (once or twice a day, no
        # fixed schedule) -- 10 minutes is far more frequent than needed
        # for that cadence, but cheap and keeps the delay between a real
        # tick and our refresh starting small.
        self._bgs_tick_timer.setInterval(10 * 60 * 1000)
        self._bgs_tick_timer.timeout.connect(self._on_bgs_tick_check_tick)
        self._bgs_tick_timer.start()
        self._bgs_tick_thread: QThread | None = None
        self._bgs_tick_worker: _BgsTickCheckWorker | None = None
```

- [ ] **Step 4: Add the tick/thread-start method and its result handler**

Add these two methods directly after `_on_market_flush_tick()` (which ends around line 3684, right before `def _refresh_squadron_station`):

```python
    def _on_bgs_tick_check_tick(self) -> None:
        if self._bgs_tick_thread and self._bgs_tick_thread.isRunning():
            return  # previous check still running -- next timer firing will catch up
        self._bgs_tick_worker = _BgsTickCheckWorker()
        self._bgs_tick_thread = QThread()
        self._bgs_tick_worker.moveToThread(self._bgs_tick_thread)
        self._bgs_tick_thread.started.connect(self._bgs_tick_worker.run)
        self._bgs_tick_worker.finished.connect(self._on_bgs_tick_check_finished)
        self._bgs_tick_worker.finished.connect(self._bgs_tick_thread.quit)
        self._bgs_tick_thread.start()

    def _on_bgs_tick_check_finished(self, tick_iso) -> None:
        self.player_faction_panel.maybe_refresh_for_tick(tick_iso)
```

- [ ] **Step 5: Compile-check**

Run: `python -m py_compile edc/ui/main_window.py`
Expected: no output (success)

- [ ] **Step 6: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: poll tick.edcd.io every 10 minutes to trigger the BGS refresh"
```

---

### Task 5: `overview_panel.py` — tick-detected HUD flash

**Files:**
- Modify: `edc/ui/panels/overview_panel.py`
- Modify: `edc/ui/main_window.py` (one line, connecting the signal)

**Interfaces:**
- Consumes: `PlayerFactionPanel.tick_refresh_started` signal (Task 3).

No automated test -- this is a visual UI element, consistent with this file's existing convention (no unit tests touch any panel's rendering). Compile-check plus live verification.

- [ ] **Step 1: Add the `QTimer` import**

In `edc/ui/panels/overview_panel.py`, the existing import at the top of the file reads:

```python
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QSize, QRect, pyqtSignal
)
```

Change it to add `QTimer`:

```python
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QSize, QRect, QTimer, pyqtSignal
)
```

- [ ] **Step 2: Add the flash label and its fade animation**

Add the new label directly after the existing `self.overview_actions` setup block (after line 274's `outer.addWidget(self.overview_actions)`, before the `# ── Scroll area ──` comment at line 276):

```python
        self._tick_flash_label = QLabel("Tick detected — updating BGS data…")
        self._tick_flash_label.setStyleSheet(
            "background-color: #0a1a0f; color: #6BCB77; padding: 4px 8px; font-weight: bold;"
        )
        self._tick_flash_opacity = QGraphicsOpacityEffect(self._tick_flash_label)
        self._tick_flash_label.setGraphicsEffect(self._tick_flash_opacity)
        self._tick_flash_opacity.setOpacity(0.0)
        self._tick_flash_label.setVisible(False)
        self._tick_flash_anim = None
        outer.addWidget(self._tick_flash_label)
```

- [ ] **Step 3: Add the show/fade method**

Add this method anywhere in the `OverviewPanel` class after `__init__` completes (e.g. directly before the existing `def refresh(self, state):` method around line 591):

```python
    def show_tick_flash(self) -> None:
        """Fades a brief notice in, holds it ~10s, fades it out -- same
        QGraphicsOpacityEffect + QPropertyAnimation pattern already used
        for overview_actions' own new-content fade, but a fully separate
        widget/effect instance so the two never interfere with each
        other's animation."""
        self._tick_flash_label.setVisible(True)
        self._tick_flash_opacity.setOpacity(0.0)

        self._tick_flash_anim = QPropertyAnimation(self._tick_flash_opacity, b"opacity")
        self._tick_flash_anim.setDuration(400)
        self._tick_flash_anim.setStartValue(0.0)
        self._tick_flash_anim.setEndValue(1.0)
        self._tick_flash_anim.start()

        QTimer.singleShot(10000, self._start_tick_flash_fadeout)

    def _start_tick_flash_fadeout(self) -> None:
        self._tick_flash_anim = QPropertyAnimation(self._tick_flash_opacity, b"opacity")
        self._tick_flash_anim.setDuration(800)
        self._tick_flash_anim.setStartValue(1.0)
        self._tick_flash_anim.setEndValue(0.0)
        self._tick_flash_anim.finished.connect(self._hide_tick_flash)
        self._tick_flash_anim.start()

    def _hide_tick_flash(self) -> None:
        self._tick_flash_label.setVisible(False)
```

- [ ] **Step 4: Wire the signal in `main_window.py`**

In `edc/ui/main_window.py`, find where `self.player_faction_panel = PlayerFactionPanel(...)` is constructed (around line 1077 — `self.overview_panel` is already constructed earlier, around line 1036, so it exists by this point) and add directly after it:

```python
        self.player_faction_panel.tick_refresh_started.connect(self.overview_panel.show_tick_flash)
```

- [ ] **Step 5: Compile-check both files**

Run: `python -m py_compile edc/ui/panels/overview_panel.py edc/ui/main_window.py`
Expected: no output (success)

- [ ] **Step 6: Live verification**

Per this project's established convention (`CLAUDE.md`: confirmation means working in-game or visually confirmed in the running app):

1. Launch the app.
2. To trigger the flash without waiting for a real tick or the full 10-minute timer: open `data/faction_refresh.json` (or wherever `self.faction_refresh_tracker`'s path resolves to), note the current `last_refreshed_tick` value (or its absence), then either delete that key or wait for the timer.
3. Confirm the Overview HUD shows the "Tick detected — updating BGS data…" flash, fading in, holding, then fading out over roughly 10-12 seconds total.
4. Confirm the Player Faction tab's full refresh actually starts (status label shows "Refreshing 0 / N…").
5. Confirm `faction_refresh.json`'s `last_refreshed_tick` updates to the new tick's timestamp once the refresh completes.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/panels/overview_panel.py edc/ui/main_window.py
git commit -m "feat: flash a brief notice on the Overview HUD when a BGS tick starts a refresh"
```
