# Elite Dangerous Little Helper

EDHelper is a Python desktop companion app for Elite Dangerous focused on live journal monitoring, current commander/game-state visibility, and historical journal import into a local SQLite database.

## What the app currently does

EDHelper currently includes:

- Live journal monitoring
- Live status monitoring
- In-memory game state tracking
- UI updates driven by incoming events
- Historical journal import
- Local SQLite persistence for selected imported data
- Exploration-related state handling
- Exobiology-related state handling
- PowerPlay-related state handling
- Item/material metadata support
- User settings management

## Current architecture at a glance

The application currently has two important runtime paths:

### 1. Live runtime path

This path handles what happens while the game is running.

Flow:

1. `edc/app.py` bootstraps the application
2. `edc/ui/main_window.py` creates the main UI
3. `MainWindow.start_auto_watch()` starts live watchers
4. `edc/core/journal_watcher.py` watches journal files and emits events
5. `edc/ui/main_window.py::_on_event(evt)` receives live events
6. `edc/core/event_engine.py::process(event)` updates in-memory state
7. `MainWindow` updates logging and refreshes UI elements

### 2. Historical import path

This path handles backfilling historical journal data into local persistence.

Flow:

1. `edc/app.py::run()` instantiates `JournalImporter`
2. `edc/core/journal_importer.py::import_all()` starts import processing
3. Journal files are parsed and normalized
4. Repository methods in `persistence/repository.py` persist imported data
5. Processed journal files are marked as imported

## Current top-level module ownership

### `edc/core`
Core runtime behavior, state management, live watchers, importer logic, and item catalog support.

Notable files:
- `event_engine.py`
- `journal_importer.py`
- `journal_watcher.py`
- `status_watcher.py`
- `state.py`
- `item_catalog.py`

### `edc/engine/handlers`
Feature-specific event handling logic.

Notable files:
- `exploration.py`
- `exobio.py`
- `inventory.py`
- `powerplay.py`

### `edc/ui`
Main UI, formatting helpers, and settings dialog.

Notable files:
- `main_window.py`
- `settings_dialog.py`
- `formatting.py`

### `persistence`
SQLite schema, connection layer, and repository/data access layer.

Notable files:
- `database.py`
- `repository.py`
- `schema.py`

## Persistence model

The historical importer currently persists data through repository methods such as:

- `save_system(...)`
- `save_body(...)`
- `save_body_signals(...)`
- `save_exobiology(...)`
- `mark_journal_processed(...)`

Live event processing currently updates in-memory state through `EventEngine` and UI logic through `MainWindow`. Historical import is the main confirmed persistence path.

## Running the application

Current startup is driven through the application bootstrap in `edc/app.py`, with `run()` acting as the main application startup function.

Recommended local workflow:

1. Activate the project virtual environment
2. Start the app through the normal project launcher/bootstrap path
3. Verify watcher startup
4. Verify live journal monitoring
5. Verify database path/settings if historical import is enabled

## Current project status

The project has a good functional foundation and clear subsystem direction, but the documentation has lagged behind the codebase.

The biggest current needs are:

- updated technical documentation
- clearer ownership boundaries
- stronger change safety
- better regression coverage for live event and import flows
- continued refactoring of large or mixed-responsibility files

## Known structural pain points

The main issues currently identified are:

- documentation drift
- unclear boundaries between some runtime components
- likely oversized or over-centralized UI orchestration in `main_window.py`
- need for stronger regression tests around live event processing and import processing
- need for better logging/debug visibility in high-risk paths

## Recommended next steps

### Documentation
- refresh `README.md`
- replace the old project structure doc with a current version
- add a practical project plan

### Change safety
- add regression tests around `EventEngine.process(...)`
- add regression tests around `JournalImporter.import_all()`
- improve event and import logging

### Structural cleanup
- continue reducing responsibility in `main_window.py`
- tighten boundaries between UI orchestration, engine logic, handlers, and importer logic
- document “where to edit for X” for future maintenance

## Project goals going forward

The immediate goal is not just to add more features, but to make the existing codebase easier and safer to maintain by:

- documenting the real runtime flows
- reducing confusion between live and historical paths
- improving testability
- improving observability
- supporting safer future enhancements
