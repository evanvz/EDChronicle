# EDChronicle

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

EDChronicle is a Python desktop companion app for Elite Dangerous built for the solo player, with a focus on Exploration, Exobiology, Combat, PowerPlay, Mining, Engineering, and Fleet Carriers. It monitors live journal entries and imports historical journals into a local SQLite database. Body enrichment data is optionally fetched from [Spansh](https://spansh.co.uk) when local journal data is insufficient, and PowerPlay system control is cross-checked against [EDSM](https://www.edsm.net) and a live [EDDN](https://github.com/EDCD/EDDN) feed. EDChronicle can also optionally contribute journal data back to EDDN, the same shared network Spansh, EDSM, and Inara all draw from.

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
- PowerPlay Target Finder tab — searches Spansh for nearby systems by mission type (reinforcement, undermining, acquisition) with distance and facility filters
- Target Finder results are cross-checked against two independent sources: a daily-refreshed EDSM PowerPlay dump and a live EDDN PowerPlay feed — agreement is confirmed, disagreement is flagged, so stale or wrong Spansh data doesn't send you to the wrong system
- Activity guide per system type driven by a local `powerplay_activities.json` config
- TTS megaship merit alert when a megaship is detected in a reinforcement or acquisition system

### Mining
- Live session stats: asteroids prospected, cores cracked, tons refined per material
- Ring/hotspot finder — searches Spansh for systems with rings containing a specific mineable material, sorted by distance from your current location

### Materials & Engineering
- Live material inventory (Raw/Manufactured/Encoded) tracked incrementally as you collect, discard, trade, or consume materials — no need to relog for counts to update
- Engineering Blueprint Wishlist tab — pick a blueprint and target grade, and EDChronicle sums material requirements cumulatively across every grade from 1 up to the target (reaching grade 5 means engineering through grades 1-4 first, each with its own material cost)
- Shows exactly which materials you're short, and how many
- Lists every known engineer who offers the selected blueprint/grade, sorted by distance from your current location, with your real unlock rank compared against what that specific grade requires
- Optional voice + Overview panel alert when you're near a farming location for a material on your wishlist

### Fleet Carrier
- Tracks carrier stats, cargo, and jump status from journal events

### Voice commands
- Say a trigger phrase to fire in-game ship actions (power distribution, cargo scoop, landing gear, etc.) via keybind dispatch — reads your actual bound keys from the game's `.binds` file
- Offline speech recognition via Vosk, with confirmation TTS feedback per command

### Voice / TTS alerts
- Text-to-speech announcements via Edge TTS (Microsoft neural voices)
- Priority queue — combat alerts interrupt lower-priority exploration cues
- Per-event TTS toggle in Settings (each event type can be enabled/disabled independently)
- NPC and system text comms read aloud via a dedicated comms audio channel
- Announcement examples: FSD jump, arrival, system PP type, first discovery, first mapping, first footfall, SAA complete, FSS complete, bio/geo/Guardian/Thargoid signals, exobiology scan progress, combat under attack

### Overview panel
- Single-screen HUD showing current system, body count, PP state, active signals, unresolved bodies, and recommended actions

## Data sources & ecosystem contribution

EDChronicle draws on the same community data network the rest of the Elite Dangerous tooling ecosystem uses:

- **[Spansh](https://spansh.co.uk)** — body enrichment, PowerPlay system search, ring/hotspot mining search
- **[EDSM](https://www.edsm.net)** — daily PowerPlay dump, used as an independent cross-check against Spansh
- **[EDDN](https://github.com/EDCD/EDDN)** — live subscription for real-time PowerPlay cross-checking, the same feed Spansh and EDSM themselves are built from

EDChronicle can also **optionally** contribute back: with "Contribute data to EDDN" enabled in Settings (off by default), a subset of your journal events (jumps, docking, scans, surface signal scans, carrier jumps, codex entries) is published to EDDN in its standard schema, benefiting every tool that consumes it — the same mechanism EDMarketConnector uses. No personal data beyond your commander name is included, and EDDN obfuscates that before distributing it further.

## Screenshots

![Overview HUD](screenshots/OverView%20Hud.png)
![Exploration](screenshots/Exploration.png)
![Planets](screenshots/Planets.png)
![Exobiology](screenshots/Exobiology.png)
![Combat](screenshots/Combat.png)
![PowerPlay](screenshots/PowerPlay.png)
![Settings](screenshots/Settings.png)

## Current architecture at a glance

The application has four main runtime paths:

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

### 4. EDDN cross-check & publish path

Cross-checks PowerPlay data and, if enabled, contributes journal events back to the network.

Flow:

1. `edc/core/eddn_listener.py` subscribes to EDDN's live ZeroMQ relay in the background and feeds PowerPlay sightings into `edc/core/eddn_powerplay.py`
2. `edc/core/edsm_powerplay.py` refreshes a daily-cached EDSM PowerPlay dump on startup (via `cloudscraper`, since the public dump sits behind a generic Cloudflare bot challenge)
3. `edc/ui/panels/powerplay_finder_panel.py` cross-checks each Spansh search result's controlling power against both sources and flags disagreement
4. On every raw journal event, `MainWindow` calls `edc/core/eddn_publisher.py::observe()` to track session header fields (commander, game version, Horizons/Odyssey flags); if "Contribute data to EDDN" is enabled in Settings, `maybe_publish()` builds a schema-compliant `journal/1` message and queues it for background delivery to the EDDN gateway

## Current top-level module ownership

### `edc/core`
Core runtime: state management, live watchers, journal importer, Spansh/EDSM/EDDN clients, PowerPlay activity table, engineering data.

Notable files:
- `event_engine.py`
- `journal_importer.py`
- `journal_watcher.py`
- `status_watcher.py`
- `state.py`
- `spansh_client.py`
- `edsm_powerplay.py` — daily-cached EDSM PowerPlay dump cross-check
- `eddn_listener.py` / `eddn_powerplay.py` — live EDDN PowerPlay subscription
- `eddn_publisher.py` — opt-in journal/1 schema publishing back to EDDN
- `powerplay_activities.py`
- `item_catalog.py`
- `engineering_blueprints.py` — blueprint material costs + which engineer(s) offer each grade
- `engineering_wishlist.py` — persisted blueprint/grade build targets
- `engineer_progress_store.py` — persisted per-engineer unlock rank/status

### `edc/engine/handlers`
Feature-specific event handling logic (state mutations driven by journal events).

Notable files:
- `exploration.py`
- `exobio.py`
- `inventory.py` — includes live material inventory deltas (collect/discard/trade/craft)
- `powerplay.py`
- `mining.py`
- `fleet_carrier.py`
- `engineers.py` — `EngineerProgress` unlock tracking

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
- `handlers/engineering.py` — wishlist material-nearby alert phrase pool

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
- `mining_panel.py`
- `engineering_panel.py`
- `fleet_carrier_panel.py`

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

### Local JSON stores (outside SQLite)

Some newer features persist to plain JSON under `settings/` or `data/` rather than the SQLite database:

| File | Contents |
|------|----------|
| `settings/engineering_blueprints.json` | Blueprint material costs per grade + which engineer(s) offer each (reference data, not user-specific) |
| `data/engineering_wishlist.json` | User-selected blueprint/grade build targets |
| `data/engineer_progress.json` | Per-engineer unlock rank/status, seeded at startup and updated on `EngineerProgress` events |
| `settings/edsm_powerplay_cache.json` | Daily-refreshed EDSM PowerPlay dump cross-check cache |
| `settings/eddn_powerplay_cache.json` | Live EDDN PowerPlay sightings collected this session |

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

Copyright © 2026 CMDR B0B R0GERS

See [LICENSE](../LICENSE) for the full license text.
