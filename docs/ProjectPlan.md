# EDHelper Project Plan

This document describes the current project state, the main issues identified, and a practical plan for stabilization and future enhancement.

## 1. Current state summary

EDHelper has a good functional base and a sensible architecture direction, but the project has outgrown its older documentation and now needs a structured stabilization phase.

Current strengths:
- clear separation between live runtime and historical import paths
- dedicated persistence layer
- feature-specific handler modules
- growing subsystem coverage across exploration, exobiology, inventory, and PowerPlay

Current pain points:
- documentation drift
- unclear ownership in some areas
- centralization risk in `main_window.py`
- need for stronger regression safety in event and import flows
- need for better debugging/logging visibility

## 2. Confirmed major issues

### A. Documentation drift
The old README and old project structure description no longer reflect the real codebase shape.

### B. Live path vs import path confusion
This required explicit re-discovery and should now be documented clearly.

### C. Change safety is too weak
High-risk files can change behavior broadly without enough regression protection.

### D. Central orchestration risk
`main_window.py` likely owns too much coordination responsibility.

### E. Runtime visibility needs improvement
Debugging and troubleshooting would benefit from stronger event/import logging and clearer runtime visibility.

## 3. Project goals

The next stage of the project should focus on:

1. making the current codebase easier to understand
2. making changes safer
3. reducing confusion between runtime paths
4. improving maintainability before major additional feature growth

## 4. Phase plan

## Phase 1 — Documentation refresh

### Goals
- rebuild project documentation to match current code
- document the real startup and runtime flows
- reduce onboarding and troubleshooting confusion

### Deliverables
- updated `README.md`
- `docs/ProjectStructure.md`
- `docs/ProjectPlan.md`

### Priority
Immediate

## Phase 2 — Change safety and observability

### Goals
- improve confidence during troubleshooting and refactoring
- reduce regression risk
- make event/import behavior easier to inspect

### Recommended work
- add regression tests around `edc/core/event_engine.py::process(...)`
- add regression tests around `edc/core/journal_importer.py::import_all()`
- add logging around:
  - journal event receipt
  - status updates
  - event-engine processing
  - importer file processing
  - repository writes
  - processed journal markers

### Priority
High

## Phase 3 — Structural cleanup

### Goals
- improve ownership boundaries
- reduce oversized orchestration logic
- make future features easier to add safely

### Recommended work
- reduce responsibility inside `edc/ui/main_window.py`
- make event/UI orchestration easier to trace
- continue clarifying `event_engine` vs handler responsibilities
- make importer helper flow easier to follow and test
- review any duplicated logic between handlers or between live/import paths

### Priority
High

## Phase 4 — Developer workflow improvements

### Goals
- make day-to-day work easier and safer
- reduce dependence on memory for changes

### Recommended work
- maintain a current project structure doc
- maintain a “where to edit for X” section
- create simple run/check scripts for local workflow
- standardize change routine:
  - inspect
  - edit
  - compile/check
  - run
  - test
  - commit

### Priority
Medium

## Phase 5 — Feature growth after stabilization

### Goals
- add new features on top of a safer base
- avoid expanding technical debt while growing the app

### Recommended rule
Do not expand major feature scope until:
- docs are current
- high-risk paths have regression tests
- runtime logging is improved
- core ownership boundaries are clearer

## 5. Suggested technical priorities

## Priority 1
Refresh docs and lock in the current architecture picture.

## Priority 2
Protect the live event path:
- `edc/core/event_engine.py`
- `edc/ui/main_window.py`

## Priority 3
Protect the historical import path:
- `edc/core/journal_importer.py`
- `persistence/repository.py`

## Priority 4
Reduce centralization in:
- `edc/ui/main_window.py`

## Priority 5
Improve runtime observability:
- event logging
- importer logging
- state/debug visibility

## 6. Testing roadmap

## Live path tests
Focus on:
- event sequences into `EventEngine.process(...)`
- expected state transitions
- expected returned messages
- high-risk feature branches such as exploration, exobiology, and PowerPlay

## Import path tests
Focus on:
- historical journal replay
- save-system/body/signals/exobiology persistence behavior
- processed-journal tracking
- malformed or partial journal inputs

## Integration tests
Focus on:
- startup/bootstrap path
- watcher startup path
- importer startup path
- basic SQLite schema/repository contract validation

## 7. Logging and debugging roadmap

Recommended additions:

### Live path
- log received event names
- log key state transitions
- log engine message outputs
- log watcher startup and shutdown

### Import path
- log file start/end
- log event counts by type
- log persistence writes/failures
- log processed-journal marks
- log skipped/unknown cases

### UI path
- log major refresh triggers
- log settings load/save issues
- log startup issues clearly

## 8. Definition of a “safe change”

A change should be considered safe only when:

1. the affected path is understood
2. the file ownership is clear
3. the change is limited in scope
4. compile/check passes
5. runtime behavior is manually verified
6. related regression coverage exists or is added
7. docs are updated if architecture or ownership changed

## 9. Practical next actions

Immediate next actions:

1. commit refreshed docs
2. identify the top 3 highest-risk files
3. add or improve logging in live and import paths
4. create regression tests for:
   - `EventEngine.process(...)`
   - `JournalImporter.import_all()`
5. start reducing responsibility in `main_window.py`

## 10. Working rule going forward

For every new enhancement, first classify it as:

- live runtime change
- historical import change
- persistence/schema change
- UI-only change
- settings/config change

That one step will keep future maintenance much cleaner.