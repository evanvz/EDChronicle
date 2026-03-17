# EDHelper Project Structure

This document describes the current codebase structure and the major runtime flows based on the current code rather than older project documentation.

## 1. Startup flow

Current startup path:

1. Top-level startup reaches the application bootstrap in `edc/app.py`
2. `edc/app.py::run()` initializes the application
3. `MainWindow` is created during startup
4. Historical import is triggered from `run()`
5. Live watchers are started through `MainWindow.start_auto_watch()`

## 2. Main runtime paths

The project currently has two primary runtime paths.

### A. Live runtime path

This path is responsible for current live gameplay monitoring and UI updates.

Flow:

1. `edc/ui/main_window.py`
   - creates `JournalWatcher`
2. `edc/core/journal_watcher.py`
   - emits `event_received`
3. `edc/ui/main_window.py`
   - connects `self.watcher.event_received.connect(self._on_event)`
4. `MainWindow._on_event(evt)`
   - receives live events
5. `self.engine.process(evt)`
   - updates in-memory state
6. `MainWindow`
   - logs messages and refreshes UI-related elements

### B. Historical import path

This path is responsible for replaying historical journal files into local persistence.

Flow:

1. `edc/app.py::run()`
   - instantiates `JournalImporter`
2. `edc/core/journal_importer.py::import_all()`
   - starts historical import
3. Import helper methods process journal files and normalize values
4. `persistence/repository.py`
   - persists systems, bodies, signals, exobiology, and processed-journal markers

## 3. Directory overview

## `edc/core`

Core runtime and state-related components.

### `event_engine.py`
Primary live event-processing engine that updates in-memory state and returns messages used by the UI layer.

### `journal_importer.py`
Historical journal import logic and repository-writing path for imported data.

### `journal_watcher.py`
Live journal watcher that monitors journal files and emits parsed events.

### `status_watcher.py`
Live status watcher for `Status.json` updates.

### `state.py`
Current in-memory game/application state.

### `item_catalog.py`
Offline metadata catalog support for items/materials.

## `edc/engine/handlers`

Feature-specific event handling helpers.

### `exploration.py`
Exploration-related event handling.

### `exobio.py`
Exobiology-related event handling.

### `inventory.py`
Inventory/material-related event handling.

### `powerplay.py`
PowerPlay-related event handling.

## `edc/ui`

UI and display layer.

### `main_window.py`
Main UI orchestration layer and live-event receiver.

### `settings_dialog.py`
User settings dialog.

### `formatting.py`
Formatting/display helper functions for the UI layer.

## `persistence`

Database and storage layer.

### `database.py`
SQLite connection and SQL execution layer.

### `repository.py`
Persistence/data-access layer for imported game data.

### `schema.py`
Schema definitions for the SQLite database.

## 4. Confirmed responsibility boundaries

## Live state path
Owned primarily by:
- `edc/core/event_engine.py`
- `edc/core/state.py`
- `edc/ui/main_window.py`

Purpose:
- receive live events
- update in-memory state
- trigger UI refresh/logging

Should not become:
- the historical import persistence path
- a dumping ground for unrelated persistence logic

## Historical import path
Owned primarily by:
- `edc/core/journal_importer.py`
- `persistence/repository.py`

Purpose:
- process historical journals
- normalize and persist imported data
- mark processed journal files

Should not become:
- the live UI update path
- the place to own unrelated display logic

## UI path
Owned primarily by:
- `edc/ui/main_window.py`
- `edc/ui/settings_dialog.py`
- `edc/ui/formatting.py`

Purpose:
- UI orchestration
- settings UI
- display formatting

Should not become:
- the main home of domain logic
- the main home of persistence rules

## 5. Persistence path

Historical import currently writes through repository methods such as:

- `save_system(...)`
- `save_body(...)`
- `save_body_signals(...)`
- `save_exobiology(...)`
- `mark_journal_processed(...)`

This persistence path is currently most clearly associated with historical import processing.

## 6. High-risk change areas

These areas deserve extra care during changes:

### `edc/ui/main_window.py`
Reason:
- central orchestration
- watcher startup
- live event reception
- UI refresh/logging interactions

### `edc/core/event_engine.py`
Reason:
- central live event-processing path
- in-memory state mutation
- potentially broad downstream effect on UI behavior

### `edc/core/journal_importer.py`
Reason:
- historical import correctness
- repository writes
- replay-based data consistency

### `persistence/repository.py`
Reason:
- persistence contract
- schema alignment
- imported data integrity

## 7. Where to edit for common changes

### Live event behavior change
Start with:
- `edc/core/event_engine.py`
- `edc/ui/main_window.py`
- `edc/core/journal_watcher.py`

### Historical import / backfill change
Start with:
- `edc/core/journal_importer.py`
- `persistence/repository.py`
- `persistence/schema.py`

### Settings/UI-only change
Start with:
- `edc/ui/main_window.py`
- `edc/ui/settings_dialog.py`
- `edc/config.py` if applicable

### Item/material metadata change
Start with:
- `edc/core/item_catalog.py`

### PowerPlay behavior change
Start with:
- `edc/engine/handlers/powerplay.py`
- `edc/core/event_engine.py`
- `edc/ui/main_window.py` if display changes are involved

## 8. Recommended documentation maintenance rule

Whenever a runtime flow changes, update:
- this file
- `README.md`
- any related roadmap/plan docs

The project has evolved enough that architecture docs should now be treated as maintained project assets, not one-time notes.