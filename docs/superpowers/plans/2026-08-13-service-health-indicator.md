# Service Health Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three always-visible status-bar indicators (EDSM / EDDN / BGS Tick) that turn red when a service's underlying modules have logged 3+ failures within the last 10 minutes, so the user can tell "in-game" that something's actually broken instead of only finding out when a specific feature quietly returns nothing.

**Architecture:** A single new `logging.Handler` subclass passively observes `WARNING`+ log records already flowing through the existing root logger (`edc/utils/log.py`'s one-and-only `FileHandler` setup) — no existing feature module is touched. `main_window.py` adds three permanent `QMainWindow.statusBar()` widgets, polled by a new `QTimer` matching this file's existing timer-setup convention.

**Tech Stack:** Python, PyQt6, stdlib `logging`.

## Global Constraints

- Zero changes to any of the six existing EDSM/EDDN/tick-touching modules — the whole point of the logging-handler design is that it observes already-happening `log.warning`/`log.exception` calls without modifying where they're made.
- Logger-name-to-service mapping is explicit, not prefix-matched (confirmed during design that naming isn't consistent enough for a prefix rule — e.g. `edc.core.colonisation_eligibility` touches EDSM but doesn't start with `edsm_`):
  ```python
  _SERVICE_LOGGERS = {
      "edc.core.edsm_faction_lookup": "EDSM",
      "edc.core.edsm_powerplay": "EDSM",
      "edc.core.colonisation_eligibility": "EDSM",
      "edc.core.eddn_listener": "EDDN",
      "edc.core.eddn_market": "EDDN",
      "edc.core.bgs_tick": "BGS Tick",
  }
  ```
- Threshold: a service is "having an issue" (red) when 3+ matched failures land within the trailing 10 minutes, aggregated across all logger names mapped to that service. Reverts to "ok" (green) once fewer than 3 failures remain within the trailing window (i.e., the window is evaluated fresh on every query, not latched until manually cleared).
- Only records at `WARNING` level or above are considered; only records whose `record.name` is an exact key in `_SERVICE_LOGGERS` are considered. Everything else passes through the handler untouched (this handler must never suppress, modify, or block a log record — it only observes).
- No new database table, no new settings file, no new persistence — this is in-memory only, reset on every app restart (matches the "live status right now" intent — history isn't the point).

---

## File Structure

- **Create:** `edc/core/service_health.py` — the handler + query functions.
- **Test:** `tests/test_service_health.py`.
- **Modify:** `edc/utils/log.py` — attach the new handler (one line).
- **Modify:** `edc/ui/main_window.py` — three status-bar widgets + polling `QTimer`.

---

### Task 1: `service_health` module

**Files:**
- Create: `edc/core/service_health.py`
- Test: `tests/test_service_health.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `attach() -> None` (idempotent — safe to call more than once, only attaches the handler the first time), `status(service: str) -> str` (`"ok"` or `"issue"`), `detail(service: str) -> str` (empty string if `"ok"`, else a human string naming the worst-offending logger and its count within the window) — Task 2 calls `attach()`, `status()`, `detail()` by exact name

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_health.py`:

```python
"""Tests for edc.core.service_health -- a passive logging.Handler that
tracks WARNING+ records from known EDSM/EDDN/tick loggers and reports a
simple ok/issue status per service, based on a 3-failures-in-10-minutes
threshold. Uses the module's internal recording function directly with
controlled timestamps for the threshold-logic tests (avoids mocking
time.monotonic across the whole test), plus one end-to-end test going
through real logging.warning() calls to confirm the handler is actually
wired up correctly."""
import logging

import pytest

from edc.core import service_health


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test gets a clean slate -- the module's tracking state is a
    module-level singleton (by design, so main_window.py doesn't need to
    thread an instance through anywhere), so tests must reset it."""
    service_health._reset_for_tests()
    yield
    service_health._reset_for_tests()


def test_no_records_means_ok():
    assert service_health.status("EDSM") == "ok"
    assert service_health.detail("EDSM") == ""


def test_below_threshold_stays_ok():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    assert service_health.status("EDSM") == "ok"


def test_three_failures_within_window_trips_issue():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"


def test_failures_across_different_edsm_modules_aggregate_to_one_service():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_powerplay", now + 1)
    service_health._record("edc.core.colonisation_eligibility", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"


def test_failures_outside_window_do_not_count():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    # Query 11 minutes later -- all three have aged out of the 10-minute window.
    assert service_health.status("EDSM", _now=now + 11 * 60) == "ok"


def test_services_are_independent():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"
    assert service_health.status("EDDN", _now=now + 2) == "ok"
    assert service_health.status("BGS Tick", _now=now + 2) == "ok"


def test_detail_names_worst_offending_logger():
    now = 1000.0
    service_health._record("edc.core.edsm_powerplay", now)
    service_health._record("edc.core.edsm_powerplay", now + 1)
    service_health._record("edc.core.edsm_powerplay", now + 2)
    service_health._record("edc.core.edsm_faction_lookup", now + 3)
    d = service_health.detail("EDSM", _now=now + 3)
    assert "edsm_powerplay" in d
    assert "3" in d


def test_unknown_service_name_is_ok_not_an_error():
    assert service_health.status("NotARealService") == "ok"


def test_end_to_end_through_real_logging_call():
    """Confirms the handler is actually wired up to intercept real
    logging.warning() calls, not just that the internal recording
    function works in isolation."""
    service_health.attach()
    logger = logging.getLogger("edc.core.edsm_faction_lookup")
    for _ in range(3):
        logger.warning("simulated EDSM failure")
    assert service_health.status("EDSM") == "issue"


def test_info_level_records_are_ignored():
    service_health.attach()
    logger = logging.getLogger("edc.core.edsm_faction_lookup")
    for _ in range(5):
        logger.info("this is not a failure")
    assert service_health.status("EDSM") == "ok"


def test_unmapped_logger_is_ignored():
    service_health.attach()
    logger = logging.getLogger("edc.core.some_unrelated_module")
    for _ in range(5):
        logger.warning("unrelated warning")
    assert service_health.status("EDSM") == "ok"
    assert service_health.status("EDDN") == "ok"


def test_attach_is_idempotent():
    service_health.attach()
    service_health.attach()
    service_health.attach()
    handler_count = sum(
        1 for h in logging.getLogger().handlers
        if isinstance(h, service_health.ServiceHealthHandler)
    )
    assert handler_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_service_health.py -v`
Expected: every test FAILs with `ModuleNotFoundError: No module named 'edc.core.service_health'`.

- [ ] **Step 3: Implement the module**

Create `edc/core/service_health.py`:

```python
"""Passive service-health tracking via a logging.Handler -- observes
WARNING+ records already flowing through the root logger from known
EDSM/EDDN/tick-touching modules (see edc/utils/log.py's single root
FileHandler setup, which every edc.* logger already propagates through)
and reports a simple ok/issue status per service group, based on a
3-failures-in-10-minutes threshold. No existing feature module is
touched -- this only observes logging calls that already happen.

Module-level singleton by design: main_window.py needs to query status
from a QTimer callback without threading a handler instance through the
constructor chain, and there's only ever one meaningful health state for
the whole running app.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Deque, Tuple

_SERVICE_LOGGERS: Dict[str, str] = {
    "edc.core.edsm_faction_lookup": "EDSM",
    "edc.core.edsm_powerplay": "EDSM",
    "edc.core.colonisation_eligibility": "EDSM",
    "edc.core.eddn_listener": "EDDN",
    "edc.core.eddn_market": "EDDN",
    "edc.core.bgs_tick": "BGS Tick",
}

_WINDOW_SECONDS = 10 * 60
_ISSUE_THRESHOLD = 3
_MAX_RECORDS_PER_LOGGER = 50

# {logger_name: deque[(timestamp, )]} -- capped per logger so a truly
# runaway failure loop can't grow this unboundedly; the 10-minute window
# means old entries age out naturally well before the cap matters in
# any realistic scenario.
_records: Dict[str, Deque[float]] = {}

_attached = False


def _record(logger_name: str, when: float) -> None:
    dq = _records.setdefault(logger_name, deque(maxlen=_MAX_RECORDS_PER_LOGGER))
    dq.append(when)


def _reset_for_tests() -> None:
    """Test-only: clears all tracked state. Not called by production code."""
    _records.clear()


class ServiceHealthHandler(logging.Handler):
    """Attached to the root logger. Never raises, never suppresses,
    never modifies a record -- purely observes WARNING+ records from
    known service loggers."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        if record.name not in _SERVICE_LOGGERS:
            return
        _record(record.name, time.monotonic())


def attach() -> None:
    """Idempotent -- safe to call more than once (e.g. if setup_logging()
    is ever re-invoked). Only attaches one handler to the root logger."""
    global _attached
    if _attached:
        return
    root = logging.getLogger()
    already = any(isinstance(h, ServiceHealthHandler) for h in root.handlers)
    if not already:
        root.addHandler(ServiceHealthHandler())
    _attached = True


def _recent_counts(service: str, now: float) -> Dict[str, int]:
    """{logger_name: count within the trailing window} for every logger
    mapped to this service."""
    counts: Dict[str, int] = {}
    for logger_name, mapped_service in _SERVICE_LOGGERS.items():
        if mapped_service != service:
            continue
        dq = _records.get(logger_name)
        if not dq:
            continue
        n = sum(1 for t in dq if now - t <= _WINDOW_SECONDS)
        if n:
            counts[logger_name] = n
    return counts


def status(service: str, _now: float | None = None) -> str:
    """"ok" or "issue" -- 3+ combined failures across every logger mapped
    to this service within the trailing 10 minutes. Unknown service names
    are always "ok" (there's nothing to report on)."""
    now = _now if _now is not None else time.monotonic()
    counts = _recent_counts(service, now)
    return "issue" if sum(counts.values()) >= _ISSUE_THRESHOLD else "ok"


def detail(service: str, _now: float | None = None) -> str:
    """Human string naming the worst-offending logger and its count
    within the window, or "" if the service is "ok"."""
    now = _now if _now is not None else time.monotonic()
    counts = _recent_counts(service, now)
    if sum(counts.values()) < _ISSUE_THRESHOLD:
        return ""
    worst_logger, worst_count = max(counts.items(), key=lambda kv: kv[1])
    short_name = worst_logger.rsplit(".", 1)[-1]
    return f"{short_name}: {worst_count} failures in {_WINDOW_SECONDS // 60} min"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_service_health.py -v`
Expected: all 13 tests PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all tests pass (100 existing plus the 13 new ones).

- [ ] **Step 6: Byte-compile check**

Run: `python -m py_compile edc/core/service_health.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add edc/core/service_health.py tests/test_service_health.py
git commit -m "feat: add passive service-health tracking via a logging handler"
```

---

### Task 2: Wire the handler in and add the status-bar indicators

**Files:**
- Modify: `edc/utils/log.py`
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `service_health.attach()`, `service_health.status(name) -> str`, `service_health.detail(name) -> str` (all from Task 1)
- Produces: nothing consumed by other tasks — this is the final task

- [ ] **Step 1: Attach the handler in `setup_logging()`**

Re-read `edc/utils/log.py` fresh (small file, low risk of drift, but confirm before editing). Add the import and one call:

```python
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from edc.core import service_health

def setup_logging(settings_dir: Path) -> None:
    logs_dir = settings_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    _purge_old_logs(logs_dir, days=2)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = logs_dir / f"edc_{timestamp}.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    service_health.attach()
```

(Only the `from edc.core import service_health` import and the final `service_health.attach()` line are new — everything else in this function is unchanged. Note `root.handlers.clear()` runs BEFORE `service_health.attach()`, so the health handler survives that clear correctly — it's added after, not before.)

- [ ] **Step 2: Add the status-bar widgets to `MainWindow`**

Re-read `edc/ui/main_window.py` fresh (flagged frequently-stale by this project's CLAUDE.md). Add the import:

```python
from edc.core import service_health
```

Directly after the existing `self._on_bgs_tick_check_tick()` line (the one with the comment about `QTimer.start()` not firing immediately — was around line 998-1002, re-confirm current location), add:

```python
        self._service_health_labels: dict[str, QLabel] = {}
        for name in ("EDSM", "EDDN", "BGS Tick"):
            lbl = QLabel(f"● {name}")
            lbl.setStyleSheet("color: #6BCB77;")  # green -- matches this app's existing "ok" color convention
            self.statusBar().addPermanentWidget(lbl)
            self._service_health_labels[name] = lbl

        self._service_health_timer = QTimer(self)
        self._service_health_timer.setInterval(30 * 1000)
        self._service_health_timer.timeout.connect(self._on_service_health_tick)
        self._service_health_timer.start()
        self._on_service_health_tick()
```

Confirm `QLabel` is already imported in this file (it is, used extensively) — no new widget import needed beyond `QTimer`, which is also already imported.

- [ ] **Step 3: Add the polling method**

Add a new method, placed near the other small `_on_*_tick()` methods in this class (e.g. near `_on_bgs_tick_check_tick`):

```python
    def _on_service_health_tick(self) -> None:
        for name, lbl in self._service_health_labels.items():
            if service_health.status(name) == "issue":
                lbl.setStyleSheet("color: #FF6B6B;")  # red -- matches this app's existing "problem" color convention
                lbl.setToolTip(service_health.detail(name))
            else:
                lbl.setStyleSheet("color: #6BCB77;")
                lbl.setToolTip("")
```

- [ ] **Step 4: Byte-compile check**

Run: `python -m py_compile edc/utils/log.py edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all tests still pass (this task adds no new automated tests — UI wiring is verified visually per this project's convention).

- [ ] **Step 6: Visual + live verification**

Launch the app (or a headless `QT_QPA_PLATFORM=offscreen` smoke check if a full launch isn't available):
- Confirm three green `● EDSM` `● EDDN` `● BGS Tick` labels appear in the status bar at the bottom of the window, visible regardless of which tab is currently selected.
- Trigger a real or simulated failure (e.g. temporarily break network access, or run a short interpreter script that calls `logging.getLogger("edc.core.edsm_faction_lookup").warning("test")` three times) and confirm the EDSM label turns red within one polling cycle (~30s), with a tooltip showing the failure detail.
- Confirm the label reverts to green once no failures remain in the trailing 10-minute window (can shortcut this check by directly calling `service_health.status()`/`detail()` with a `_now` far enough in the future rather than waiting 10 real minutes).

- [ ] **Step 7: Commit**

```bash
git add edc/utils/log.py edc/ui/main_window.py
git commit -m "feat: add EDSM/EDDN/BGS Tick status-bar health indicators"
```
