# EDChronicle

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

EDChronicle is a Python desktop companion app for Elite Dangerous built for the solo player, with a focus on Exploration, Exobiology, Combat, and PowerPlay. It monitors live journal entries and imports historical journals into a local SQLite database. Body enrichment data is optionally fetched from [Spansh](https://spansh.co.uk) when local journal data is insufficient.

## Inspiration

Inspired by [EDCoPilot](https://www.razzafrag.com/) by CMDR RazzaFrag.

## What the app currently does

### Exploration
- Live journal monitoring and in-memory game state tracking
- Historical journal import with full backfill into local SQLite database
- Tracks all scanned bodies per system: planet class, distance, estimated value, landable status
- Detects and displays body signals: biological, geological, Guardian, Thargoid, human
- Tracks first discovery, first mapping, and first footfall status per body
- Planet detail popup with full physical stats: gravity, radius, surface temperature, pressure, atmosphere type and composition, volcanism, tidal lock, mass
- Physical stats backfilled from Spansh when original journal files are no longer on disk
- Full system scan (FSS) progress tracking

### Exobiology
- Tracks genus, species, and variant per body
- Sample progress tracking (1 / 2 / 3 per organism)
- Estimated credit value per species with configurable high-value multiplier
- Codex entry logging and DSS genus discovery tracking

### Combat
- Kill tracking and bounty logging per session
- Unsold combat total with persistent session ledger

### PowerPlay
- Live system type detection on every jump: reinforcement, undermining, or acquisition
- Displays controlling power, PP state, reinforcement score, and undermining score
- PowerPlay Finder tab — searches Spansh for nearby systems by mission type (reinforcement, undermining, acquisition) with distance and value filters
- Activity guide per system type driven by a local `powerplay_activities.json` config
- TTS megaship merit alert when a megaship is detected in a reinforcement or acquisition system

### Voice / TTS alerts
- Text-to-speech announcements via Edge TTS (Microsoft neural voices)
- Priority queue — combat alerts interrupt lower-priority exploration cues
- Per-event TTS toggle in Settings (each event type can be enabled/disabled independently)
- NPC and system text comms read aloud via a dedicated comms audio channel
- Voice command recognition via Vosk (offline, no cloud dependency)
- Announcement examples: FSD jump, arrival, system PP type, first discovery, first mapping, first footfall, SAA complete, FSS complete, bio/geo/Guardian/Thargoid signals, exobiology scan progress, combat under attack

### Overview panel
- Single-screen HUD showing current system, body count, PP state, active signals, unresolved bodies, and recommended actions

## Screenshots

![Overview HUD](screenshots/OverView%20Hud.png)
![Exploration](screenshots/Exploration.png)
![Planets](screenshots/Planets.png)
![Exobiology](screenshots/Exobiology.png)
![Combat](screenshots/Combat.png)
![PowerPlay](screenshots/PowerPlay.png)
![Settings](screenshots/Settings.png)

## Current architecture at a glance

The application has three main runtime paths:

### 1. Live runtime path

Handles all in-game events while playing.

Flow:

1. `edc/app.py` bootstraps the application
2. `edc/ui/main_window.py` creates the main UI
3. `MainWindow.start_auto_watch()` starts live journal and status watchers
4. `edc/core/journal_watcher.py` watches journal files and emits events
5. `edc/ui/main_window.py::_on_event(evt)` receives live events
6. `edc/core/event_engine.py::process(event)` updates in-memory state
7. `MainWindow` refreshes UI panels and routes events to TTS

### 2. Historical import path

Backfills historical journal data into local SQLite on startup.

Flow:

1. `edc/app.py` prepares an `import_runner` and passes it to `SplashScreen`
2. `SplashScreen` runs the import in a background thread, showing live progress
3. `edc/core/journal_importer.py::import_all()` processes all unprocessed journal files
4. Repository methods in `persistence/repository.py` persist systems, bodies, exobiology, and signals
5. Processed journal files are marked to prevent re-import on subsequent startups
6. Main window only opens after the import completes

### 3. Spansh enrichment path

Fetches body data for the current system when local journal data is missing or incomplete.

Flow:

1. On `FSDJump` or `Location`, `MainWindow` triggers a background `SpanshWorker`
2. `edc/core/spansh_client.py` queries the Spansh API for the current system
3. Physical stats (gravity, radius, temperature, pressure, atmosphere, etc.) are saved to `spansh_bodies` for all bodies — including already-scanned ones — so they can backfill NULL fields in older records
4. `edc/ui/system_data_loader.py` merges Spansh stats into existing body recs for any fields that are still NULL after journal loading

## Current top-level module ownership

### `edc/core`
Core runtime: state management, live watchers, journal importer, Spansh client, PowerPlay activity table.

Notable files:
- `event_engine.py`
- `journal_importer.py`
- `journal_watcher.py`
- `status_watcher.py`
- `state.py`
- `spansh_client.py`
- `powerplay_activities.py`
- `item_catalog.py`

### `edc/engine/handlers`
Feature-specific event handling logic (state mutations driven by journal events).

Notable files:
- `exploration.py`
- `exobio.py`
- `inventory.py`
- `powerplay.py`

### `edc/audio`
TTS engine, audio playback, voice command recognition, and per-feature phrase banks.

Notable files:
- `tts_engine.py` — Edge TTS synthesis, priority queue, miniaudio playback
- `_alert_edge_proc.py` — alert audio playback subprocess
- `_comms_edge_proc.py` — comms channel audio subprocess
- `voice_commands.py` — Vosk offline voice recognition
- `handlers/exploration.py` — exploration TTS phrase pools
- `handlers/powerplay.py` — PowerPlay TTS phrase pools
- `handlers/combat.py` — combat TTS phrase pools
- `handlers/exobiology.py` — exobiology TTS phrase pools

### `edc/ui`
Main window, splash screen, system data loader, formatting helpers, and settings dialog.

Notable files:
- `main_window.py`
- `splash_screen.py`
- `system_data_loader.py`
- `planet_detail_dialog.py`
- `settings_dialog.py`
- `formatting.py`

### `edc/ui/panels`
Individual tab panels rendered within the main window.

Notable files:
- `overview_panel.py`
- `exploration_panel.py`
- `exobiology_panel.py`
- `combat_panel.py`
- `powerplay_panel.py`
- `powerplay_finder_panel.py`

### `persistence`
SQLite schema, connection layer, repository/data access layer, and schema version migrations.

Notable files:
- `database.py` — connection management and `run_migrations()` for schema upgrades
- `repository.py` — all read/write operations
- `schema.py` — table definitions

## Persistence model

### Tables

| Table | Contents |
|-------|----------|
| `systems` | Visited systems: name, body count, FSS complete, first/last visit, visit count |
| `bodies` | Scanned planets: class, distance, value, signals, physical stats (gravity, radius, temp, pressure, atmosphere, composition, tidal lock, first discovered/mapped) |
| `body_signals` | Bio, geo, and human signal counts per body |
| `spansh_bodies` | Spansh-sourced body data used when journal data is missing |
| `exobiology` | Genus, species, variant, and sample count per body |
| `codex_entries` | Codex entry ID, name, and base value per organism |
| `dss_genus_discovery` | Genus discoveries recorded via DSS scan |
| `processed_journals` | Journal files already imported (file name + size) |
| `schema_version` | Tracks DB schema version for controlled migrations |

### Schema migrations

`database.py::run_migrations()` runs on every startup and applies any pending `ALTER TABLE` statements safely (wrapped in try/except so already-existing columns are silently skipped). A `schema_version` table tracks which version the DB is on. Version upgrades can trigger one-time actions such as clearing `processed_journals` to force a full journal re-import when new columns need backfilling.

## Development tooling

| Tool | Purpose |
|------|---------|
| Visual Studio Code | Primary IDE |
| Claude Code (VS Code extension) | AI-assisted analysis, architecture discussion, and code changes |
| Python venv (Windows) | Isolated runtime environment |
| Git | Version control |
| GitHub | Remote repository and release tracking |

## Installation

Requires Python 3.10 or later — download from [python.org](https://www.python.org/downloads/).

1. Download or clone this repository
2. From the project root, run:

```
install.bat
```

This creates a Python virtual environment and installs all dependencies. It is safe to run more than once — if the virtual environment already exists it is left untouched and only new or changed dependencies are installed.

## Running the application

```
launch.bat
```

Double-click `launch.bat` from anywhere — it always resolves paths relative to the project folder. If the virtual environment is not found it will tell you to run `install.bat` first.

> **First launch note:** On first run, EDChronicle will import all your existing journal files into its local database. This can take a minute or two depending on how many journals you have. Progress is shown on the startup screen. Subsequent launches are fast — only new journals are processed.

## Updating

```
git pull
install.bat
```

`install.bat` is safe to re-run after an update — it will not recreate the virtual environment, only install any newly added dependencies.

## Feedback, suggestions and issues

Have a feature request, found a bug, or want to suggest an improvement?

Open an issue on GitHub: [github.com/evanvz/EDChronicle/issues](https://github.com/evanvz/EDChronicle/issues)

All feedback is welcome — whether it's a crash report, a missing feature, or an idea to make the app better for solo commanders.

## Support the project

EDChronicle is free and open-source. If it adds value to your gameplay, a coffee is always appreciated.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

## A note on indie development

This project is built and maintained by a solo developer in personal time. If you use, share, or build on EDChronicle, please respect the work that went into it:

- Credit the original project and author in any derivative work
- Do not redistribute modified versions without clearly noting the changes made
- A link back to this repository is always appreciated

## License

MIT License — free to use, modify and distribute, provided the original copyright notice and author credit are retained in all copies or substantial portions of the software.

Copyright © 2026 Evan van Zyl (bobrogers_solo)

See [LICENSE](../LICENSE) for the full license text.
