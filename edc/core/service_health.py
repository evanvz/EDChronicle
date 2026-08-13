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
