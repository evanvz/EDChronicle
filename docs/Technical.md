# EDChronicle — Technical Overview

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3 |
| UI framework | PyQt5 |
| Database | SQLite (via built-in `sqlite3`) |
| Audio | sounddevice |
| Packaging | Python venv (Windows) |

## Directory layout

```
edc/
  app.py                  # Application bootstrap and entry point
  core/
    event_engine.py       # Live event processing, in-memory state updates
    journal_watcher.py    # Watches live journal files, emits events
    journal_importer.py   # Historical journal import into SQLite
    status_watcher.py     # Watches Status.json for live game state
    state.py              # In-memory game/commander state
    item_catalog.py       # Offline item/material metadata
  engine/
    handlers/
      exploration.py      # Exploration event handling
      exobio.py           # Exobiology event handling
      inventory.py        # Inventory/material event handling
      powerplay.py        # PowerPlay event handling
      combat.py           # Combat event handling
  ui/
    main_window.py        # Main window, live event receiver, UI orchestration
    panels/               # Feature-specific UI panels
    settings_dialog.py    # User settings dialog
    formatting.py         # Display formatting helpers
persistence/
  database.py             # SQLite connection and query layer
  repository.py           # Data access layer for game data
  schema.py               # SQLite schema definitions
docs/
  README.md               # Project overview
  Technical.md            # This file
```

## Runtime paths

### Live path

Runs while the game is active.

1. `journal_watcher.py` monitors the Elite Dangerous journal directory and emits parsed events
2. `main_window.py` receives events via Qt signal and passes them to `event_engine.py`
3. `event_engine.py` updates in-memory state and delegates to feature handlers
4. `main_window.py` refreshes UI panels based on updated state

### Historical import path

Runs at startup to backfill local data from past journal files.

1. `app.py` instantiates `JournalImporter`
2. `journal_importer.py` replays historical journal files
3. Parsed data is written to SQLite via `repository.py`
4. Processed journal files are marked to avoid re-import

## Persistence

Only the historical import path writes to SQLite. Live event processing updates in-memory state only. Key repository methods:

- `save_system(...)` / `save_body(...)` — exploration data
- `save_body_signals(...)` — FSS/DSS signal data
- `save_exobiology(...)` — exobiology scan data
- `mark_journal_processed(...)` — import tracking
