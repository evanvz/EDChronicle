# Service Health Indicator — Design

## Context

Every EDSM/EDDN-touching feature built this session already fails soft
and logs (`log.warning`/`log.exception`) — several newer ones
(Colonisation Candidates, Fleet Carrier Materials) already show a distinct
"Lookup failed" message in their own UI. But there's no centralized
signal anywhere: each feature's failure state is siloed to itself, and
the only current detection mechanism is a human noticing a feature acting
wrong and someone reading the log file — exactly how the EDSM
User-Agent block and the 720/hour rate-limit outage were both diagnosed
earlier this session, after the fact, reactively.

## Research

`edc/utils/log.py::setup_logging()` attaches exactly one handler (a
`FileHandler`) to the ROOT logger, and every module in this codebase logs
via `logging.getLogger(__name__)` — meaning every `edc.*` logger already
propagates through that one root handler by default. This is the key
architectural fact this design relies on: a second handler can passively
observe every `WARNING`+ log record from the relevant modules without
touching any of those modules' own code.

The known live-external-source-touching loggers, confirmed by reading
each module's `logging.getLogger(__name__)` call:

| Logger name | Service |
|---|---|
| `edc.core.edsm_faction_lookup` | EDSM |
| `edc.core.edsm_powerplay` | EDSM |
| `edc.core.colonisation_eligibility` | EDSM |
| `edc.core.eddn_listener` | EDDN |
| `edc.core.eddn_market` | EDDN |
| `edc.core.bgs_tick` | BGS Tick |

## Design

### 1. `edc/core/service_health.py` (new)

`ServiceHealthHandler(logging.Handler)` — attached to the root logger
alongside the existing `FileHandler` (one new line in
`setup_logging()`, that function's only change). On every log record at
`WARNING` level or above, checks `record.name` against the table above;
matched records get `(timestamp, logger_name)` appended to a small
per-service `deque` (capped, e.g. 50 entries). Non-matching records and
records below `WARNING` are ignored — this handler never blocks, modifies,
or filters normal logging.

Public read API:
```python
def status(service: str) -> str:  # "ok" | "issue"
def detail(service: str) -> str:  # e.g. "edsm_powerplay: 5 failures in 10 min" or ""
```

### 2. Threshold

A service is "having an issue" when **3+ failures land within the last 10
minutes** (tracked per logger name, aggregated to service-level for the
`status()` result). One isolated blip that a retry already recovered from
won't trip it; a real sustained problem (this session's real EDSM
720/hour outage logged 1000+ failures within an hour) trips almost
immediately. No explicit "success" tracking — a failure-only observer has
no other option, and "no news is good news" already matches how every
other feature in this app behaves when things are fine.

### 3. UI — `edc/ui/main_window.py`

Three permanent status-bar widgets (`QMainWindow.statusBar()`, currently
unused) — `● EDSM`, `● EDDN`, `● BGS`, each a small colored dot + label.
Green by default, red when that service's threshold is tripped, back to
green once the tripping failures age out of the 10-minute window. A
`QTimer` (~30s) polls `service_health.status()`/`detail()` per service and
updates dot color + tooltip. Hovering a red dot shows the specific failing
module and count (e.g. `edsm_powerplay: 5 failures in 10 min`), so a red
EDSM dot tells you which of the 3 EDSM-touching features is actually the
problem, not just that something EDSM-related is unhappy.

### 4. Testing

The handler's core logic (per-logger deque, 10-minute window, 3-failure
threshold, service aggregation) is fully synthetic-testable — feed it
fake `logging.LogRecord`s with controlled timestamps and logger names,
assert `status()`/`detail()` transitions, including the window-expiry
reset. UI wiring (dot color/tooltip updates, the polling timer) verified
live, matching this project's convention for panel-level changes.
