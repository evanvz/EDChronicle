# EDChronicle

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

EDChronicle is a Python desktop companion app for Elite Dangerous built for the solo player, with a focus on Exploration, Exobiology, Combat, PowerPlay, Background Simulation (BGS)/Player Faction tracking, Market trading, Mining, Engineering, and Fleet Carriers. It monitors live journal entries and imports historical journals into a local SQLite database. Body enrichment data is optionally fetched from [Spansh](https://spansh.co.uk) when local journal data is insufficient, POI/codex intel comes from [Canonn](https://canonn.tech), and PowerPlay system control is cross-checked against [EDSM](https://www.edsm.net) and a live [EDDN](https://github.com/EDCD/EDDN) feed. EDChronicle can also optionally contribute journal data back to EDDN, the same shared network Spansh, EDSM, and Inara all draw from.

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
- Ring hotspot tracking: shows which bodies in the current system have rings, whether you've personally DSS'd them (with discovered materials), and flags rings with no community hotspot data anywhere (Spansh/EDDN) yet — a genuine "be first to report" gap, distinct from just not having scanned it yourself. Scan history persists across sessions and is backfilled from full journal history.
- Canonn community intel: unclaimed Codex entries known for the current system, and the nearest unclaimed Codex challenge galaxy-wide

### Exobiology
- Tracks genus, species, and variant per body
- Sample progress tracking (1 / 2 / 3 per organism)
- Estimated credit value per species with configurable high-value multiplier
- Codex entry logging and DSS genus discovery tracking

### Combat
- Combat Contacts table: every ship you've scanned this session, with rank, faction, Power, bounty, and legal status
- Confirmed-safe-target detection based on actual Elite Dangerous Crime & Punishment rules (not guessed): a `Hostile` legal status is flagged as safe to engage anywhere, PowerPlay enemies are flagged in any system your pledged Power actively contests (controls, is contesting/undermining, or the system is Contested — not just systems it already controls), and high-value bounty targets (Dangerous+/500k+/Wanted) are flagged everywhere
- BGS squadron-war context: shown as an informational note when a scanned ship's faction is at active War/Civil War with your squadron-aligned faction — not treated as a free kill, since that requires an actual Conflict Zone engagement
- Warns when your current ship (from live `Loadout` tracking) has no weapons fitted at all, regardless of the target
- Notoriety tracking with decay info, separate from active bounties
- Interstellar Factors bounty clearance: tracks outstanding `CommitCrime` bounties per issuing faction and finds the closest station you've personally confirmed offers Interstellar Factors (excluding stations owned by the issuing faction, which can't clear it)

### PowerPlay
- Live system type detection on every jump: reinforcement, undermining, or acquisition
- Displays controlling power, PP state, reinforcement score, and undermining score
- PowerPlay Target Finder tab — searches Spansh for nearby systems by mission type (reinforcement, undermining, acquisition) with distance and facility filters
- Target Finder results are cross-checked against two independent sources: a daily-refreshed EDSM PowerPlay dump and a live EDDN PowerPlay feed — agreement is confirmed, disagreement is flagged, so stale or wrong Spansh data doesn't send you to the wrong system
- Activity guide per system type driven by a local `powerplay_activities.json` config
- TTS megaship merit alert when a megaship is detected in a reinforcement or acquisition system
- Local Faction BGS card: the current system's controlling minor faction's BGS state, since Power control is ultimately backed by the local BGS

### Player Faction (BGS)
- Tracks your squadron-aligned minor faction (detected from `SquadronFaction:true` in the journal) across every system it has a presence in — not just systems you've personally visited
- Network-wide presence tracking via a live EDDN subscription, matching your squadron's faction by name across all commanders' traffic — surfaces far more systems than personal visits alone would
- Bulk import from an Inara faction-presence CSV export, resolved live via EDSM per system, with retry-on-block (EDSM sits behind Cloudflare) and skip-already-known-systems on re-import
- Manual add/remove for systems EDSM doesn't independently confirm, and stale-system reconciliation after a CSV re-import (systems no longer in the latest export are flagged for review, not silently dropped)
- Per-system recommended BGS action (e.g. "War active — combat kills help win it", "Expansion pending — keep up trade/missions/bounties") with War/Civil War/Election rows highlighted
- Active-mission tracking: which of your currently accepted missions help the squadron-aligned faction
- Sortable systems table (influence, reputation, active/pending states)

### Squadron
- Squadron name, rank, rank history, and trophies from journal-exposed squadron events (the game does not expose a member roster, chat, or wing-mission data to third-party tools)
- Points to the Player Faction tab for the squadron's BGS data

### Market / Trading
- Manual search: best price to sell, or cheapest place to buy, a given commodity within a configurable radius — backed by a galaxy-wide EDDN commodity feed, not just your own visits
- Sortable results (price, distance, demand/stock — numeric, not alphabetical) with "Updated" shown as relative time ("3h ago") instead of a raw timestamp
- Click a result to copy the station/system name, or pin it as your active destination — shown as a persistent banner on the Overview tab (surviving a crash/restart) until you dock there or dismiss it manually
- Automatic Trade Opportunities: cross-references your current market's buy prices against known sell prices elsewhere within range
- "In Cargo — Sell At" tracking that persists across jumps and undocking

### Mining
- Live session stats: asteroids prospected, cores cracked, tons refined per material
- Ring/hotspot finder — searches Spansh for systems with rings containing a specific mineable material, sorted by distance from your current location
- "Where to sell" cross-references refined cargo against known market prices within range

### Materials & Engineering
- Live material inventory (Raw/Manufactured/Encoded) tracked incrementally as you collect, discard, trade, or consume materials — no need to relog for counts to update
- Engineering Blueprint Wishlist tab — pick a blueprint and target grade, and EDChronicle sums material requirements cumulatively across every grade from 1 up to the target (reaching grade 5 means engineering through grades 1-4 first, each with its own material cost)
- Shows exactly which materials you're short, and how many
- Lists every known engineer who offers the selected blueprint/grade, sorted by distance from your current location, with your real unlock rank compared against what that specific grade requires
- Optional voice + Overview panel alert when you're near a farming location for a material on your wishlist

### Fleet Carrier
- Tracks carrier stats, cargo, and jump status from journal events, reconstructed from full journal history at startup so state survives app restarts
- Shows your squadron's shared fleet carrier separately from your own, so it's never mistaken for your personal carrier

### Odyssey
- On-foot inventory tracking (Items, Components, Data, Consumables) from Odyssey suit/backpack events

### Intel
- External points of interest and farming location matches for the current system, cross-referenced against community data

### Voice commands
- Say a trigger phrase to fire in-game ship actions (power distribution, cargo scoop, landing gear, etc.) via keybind dispatch — reads your actual bound keys from the game's `.binds` file
- Separate tab-navigation trigger phrase to switch tabs by voice (e.g. "hud combat", "hud market") — 14 of 17 tabs are voice-navigable
- Offline speech recognition via Vosk, with a dedicated PTT-style radio-click cue tone (not a raw beep) for trigger-heard/unrecognized feedback, at an independently configurable feedback volume

### Voice / TTS alerts
- Text-to-speech announcements via Edge TTS (Microsoft neural voices)
- Priority queue — combat alerts interrupt lower-priority exploration cues
- Per-event TTS toggle in Settings (each event type can be enabled/disabled independently)
- NPC and system text comms read aloud via a dedicated comms audio channel, automatically cut short the moment you jump out of the system (rather than continuing to play NPC chatter for a system you've already left)
- Announcement examples: FSD jump, arrival, system PP type, first discovery, first mapping, first footfall, SAA complete, FSS complete, bio/geo/Guardian/Thargoid signals, exobiology scan progress, combat under attack

### Overview panel
- Single-screen HUD showing current system, body count, PP state, active signals, unresolved bodies, and recommended actions
- Persistent banners for: active Market destination, squadron faction presence, engineering wishlist materials nearby, and Canonn Codex intel
- A live Shutdown journal event (game closed) starts a delayed app auto-close with a spoken goodbye, skipped during startup catch-up and cancelled if the game restarts quickly

## Data sources & ecosystem contribution

EDChronicle draws on the same community data network the rest of the Elite Dangerous tooling ecosystem uses:

- **[Spansh](https://spansh.co.uk)** — body enrichment, PowerPlay system search, ring/hotspot mining search, ring hotspot community-data gaps
- **[EDSM](https://www.edsm.net)** — daily PowerPlay dump (independent cross-check against Spansh), and per-system faction lookups for Player Faction CSV import
- **[EDDN](https://github.com/EDCD/EDDN)** — live subscription for real-time PowerPlay cross-checking, network-wide squadron faction presence tracking, and the galaxy-wide commodity price feed behind the Market tab — the same feed Spansh and EDSM themselves are built from
- **[Canonn](https://canonn.tech)** — community-sourced Codex/POI intel for the current system and nearest unclaimed Codex challenge
- **[Inara](https://inara.cz)** — optional bulk CSV export of a minor faction's full system presence list, for the Player Faction tab's bulk import

EDChronicle can also **optionally** contribute back: with "Contribute data to EDDN" enabled in Settings (off by default), a subset of your journal events (jumps, docking, scans, surface signal scans, carrier jumps, codex entries) is published to EDDN in its standard schema, benefiting every tool that consumes it — the same mechanism EDMarketConnector uses. No personal data beyond your commander name is included, and EDDN obfuscates that before distributing it further.

## Screenshots

![Overview HUD](docs/screenshots/OverView%20Hud.png)
![Exploration](docs/screenshots/Exploration.png)
![Planets](docs/screenshots/Planets.png)
![Exobiology](docs/screenshots/Exobiology.png)
![Combat](docs/screenshots/Combat.png)
![PowerPlay](docs/screenshots/PowerPlay.png)
![Settings](docs/screenshots/Settings.png)

## Current architecture at a glance

The application has five main runtime paths:

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
4. Repository methods in `persistence/repository.py` persist systems, bodies, exobiology, signals, and ring scan history
5. Processed journal files are marked to prevent re-import on subsequent startups
6. Main window only opens after the import completes; a schema-version bump can force a one-time full re-import when new columns/tables need backfilling

### 3. Spansh enrichment path

Fetches body and ring data for the current system when local journal/community data is missing or incomplete.

Flow:

1. On `FSDJump` or `Location`, `MainWindow` triggers background workers for body enrichment, ring hotspot gap checking, and Canonn intel
2. `edc/core/spansh_client.py` queries the Spansh API for the current system's bodies and ring hotspot signals
3. Physical stats (gravity, radius, temperature, pressure, atmosphere, etc.) are saved to `spansh_bodies` for all bodies — including already-scanned ones — so they can backfill NULL fields in older records
4. `edc/ui/system_data_loader.py` merges Spansh stats into existing body recs for any fields that are still NULL after journal loading

### 4. EDDN cross-check, publish & network-wide tracking path

Cross-checks PowerPlay data, tracks squadron faction presence and galaxy-wide commodity prices, and, if enabled, contributes journal events back to the network.

Flow:

1. `edc/core/eddn_listener.py` subscribes to EDDN's live ZeroMQ relay in the background, feeding PowerPlay sightings into `edc/core/eddn_powerplay.py`, commodity/faction sightings into `edc/core/eddn_market.py`, and journal-schema messages more broadly
2. `edc/core/edsm_powerplay.py` refreshes a daily-cached EDSM PowerPlay dump on startup (via `cloudscraper`, since the public dump sits behind a generic Cloudflare bot challenge)
3. `edc/ui/panels/powerplay_finder_panel.py` cross-checks each Spansh search result's controlling power against both sources and flags disagreement
4. `eddn_market.py` buffers commodity prices and squadron-faction sightings in memory and flushes to SQLite periodically in a batch, rather than writing per-message
5. On every raw journal event, `MainWindow` calls `edc/core/eddn_publisher.py::observe()` to track session header fields (commander, game version, Horizons/Odyssey flags); if "Contribute data to EDDN" is enabled in Settings, `maybe_publish()` builds a schema-compliant `journal/1` message and queues it for background delivery to the EDDN gateway

### 5. Player Faction (BGS) tracking path

Builds and maintains the full system-presence list for your squadron-aligned minor faction.

Flow:

1. `edc/core/squadron_scanner.py` scans full journal history at startup to detect the squadron-aligned faction and any already-known presence
2. Live `Docked`/`FSDJump`/`Location` events save a faction snapshot for the current system (`faction_snapshots` table) via `MainWindow._save_faction_snapshots()`
3. The EDDN network-wide listener (path 4) supplies presence data for systems never personally visited
4. `edc/core/edsm_faction_lookup.py` + `edc/core/inara_faction_csv.py` support manual add and bulk CSV import, resolving each system live against EDSM with retry-on-block
5. `edc/ui/panels/player_faction_panel.py` renders the combined result; the bulk table rebuild is decoupled from live event cadence (only on tab-show or a periodic timer) to stay responsive at hundreds of tracked systems, with single-system targeted updates on arrival

## Current top-level module ownership

### `edc/core`
Core runtime: state management, live watchers, journal importer, Spansh/EDSM/EDDN/Canonn clients, PowerPlay activity table, BGS/combat lookups, engineering data.

Notable files:
- `event_engine.py`
- `journal_importer.py`
- `journal_watcher.py`
- `status_watcher.py`
- `state.py`
- `spansh_client.py`
- `edsm_powerplay.py` — daily-cached EDSM PowerPlay dump cross-check
- `edsm_faction_lookup.py` — per-system faction lookup (with Cloudflare-block retry) for Player Faction add/import
- `eddn_listener.py` / `eddn_powerplay.py` — live EDDN PowerPlay subscription
- `eddn_market.py` — buffered EDDN commodity price + squadron faction sighting ingestion
- `eddn_publisher.py` — opt-in journal/1 schema publishing back to EDDN
- `canonn_client.py` — Canonn Codex/POI community intel
- `inara_faction_csv.py` — parses Inara's faction-presence CSV export format
- `bgs_conflicts.py` — finds who your squadron faction is at active war with, in the current system
- `ship_loadout.py` — classifies current ship hardpoints as armed/unarmed from `Loadout` events
- `bounty_scanner.py` / `notoriety_scanner.py` / `squadron_scanner.py` / `carrier_scanner.py` / `mission_scanner.py` — full-journal-history scanners that reconstruct current state at startup (bounties, notoriety, squadron, fleet carrier, active missions)
- `squadron_events.py` / `mission_events.py` — shared event-application logic used by both the live engine and the corresponding `_scanner.py`
- `market_destination.py` — persists the currently pinned Market-tab destination
- `ring_signals.py` — shared ring-name/hotspot parsing used by both the live event engine and the historical importer
- `farming_locations.py` / `external_intel.py` — community-sourced farming location and POI data for the Intel tab
- `station_pads.py` — landing pad size detection/heuristics
- `ship_command_dispatcher.py` — sends keybind-mapped input to the game window for voice ship commands
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
- `fleet_carrier.py` — includes squadron-vs-personal carrier detection
- `engineers.py` — `EngineerProgress` unlock tracking
- `misc.py`

### `edc/audio`
TTS engine, audio playback, voice command recognition, and per-feature phrase banks.

Notable files:
- `tts_engine.py` — Edge TTS synthesis, priority queue, miniaudio playback, separate main/comms channels
- `_alert_edge_proc.py` — alert audio playback subprocess
- `_comms_edge_proc.py` — comms channel audio subprocess (also source of the PTT radio-click DSP used for voice-command cue tones)
- `voice_commands.py` — Vosk offline voice recognition (ship commands + tab-navigation phrases)
- `audio_devices.py` — playback/capture device resolution
- `handlers/exploration.py` — exploration TTS phrase pools
- `handlers/powerplay.py` — PowerPlay TTS phrase pools
- `handlers/combat.py` — combat TTS phrase pools
- `handlers/exobiology.py` — exobiology TTS phrase pools
- `handlers/engineering.py` — wishlist material-nearby alert phrase pool
- `handlers/status.py`

### `edc/ui`
Main window, splash screen, system data loader, formatting helpers, settings dialog, and the shared design system.

Notable files:
- `main_window.py`
- `splash_screen.py`
- `system_data_loader.py`
- `planet_detail_dialog.py`
- `settings_dialog.py`
- `formatting.py`
- `theme.py` — shared semantic color palette and type scale
- `watcher_controller.py`

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
- `market_panel.py`
- `engineering_panel.py`
- `fleet_carrier_panel.py`
- `player_faction_panel.py`
- `squadron_panel.py`
- `intel_panel.py`
- `inventory_panel.py` — `ShiplockerPanel` (Odyssey) and `MaterialsPanel`
- `voice_commands_panel.py`

### `persistence`
SQLite schema, connection layer, repository/data access layer, and schema version migrations.

Notable files:
- `database.py` — connection management, WAL mode, and `run_migrations()` for schema upgrades
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
| `rings` | Per-ring scan status, discovered hotspot materials, and distance — personal history, backfilled from full journal history |
| `exobiology` | Genus, species, variant, and sample count per body |
| `codex_entries` | Codex entry ID, name, and base value per organism |
| `dss_genus_discovery` | Genus discoveries recorded via DSS scan |
| `faction_snapshots` | Per-system, per-day BGS snapshot (influence, states, controlling status) for the squadron-aligned faction, from journal visits and EDDN |
| `dismissed_faction_systems` | Systems manually hidden from the Player Faction tab |
| `station_info` | Ground-truth landing pad counts and station services from your own `Docked` events |
| `market_prices` | Galaxy-wide commodity prices from the EDDN commodity feed, keyed by market + commodity |
| `system_coords` | System coordinates harvested passively from EDDN journal messages, used for Market tab distance filtering |
| `commodity_names` | Internal-name → display-name mapping, seeded from your own `Market.json` visits |
| `processed_journals` | Journal files already imported (file name + size) |
| `schema_version` | Tracks DB schema version for controlled migrations |

### Schema migrations

`database.py::run_migrations()` runs on every startup and applies any pending `ALTER TABLE`/`CREATE TABLE` statements safely (wrapped in try/except so already-existing columns/tables are silently skipped). A `schema_version` table tracks which version the DB is on. Version upgrades can trigger one-time actions such as clearing `processed_journals` to force a full journal re-import when new columns or tables need backfilling.

### Local JSON stores (outside SQLite)

Some newer features persist to plain JSON under `settings/` or `data/` rather than the SQLite database:

| File | Contents |
|------|----------|
| `settings/engineering_blueprints.json` | Blueprint material costs per grade + which engineer(s) offer each (reference data, not user-specific) |
| `settings/voice_commands.json` | Ship command bindings, tab-navigation trigger word, input/output audio device, feedback volume |
| `data/engineering_wishlist.json` | User-selected blueprint/grade build targets |
| `data/engineer_progress.json` | Per-engineer unlock rank/status, seeded at startup and updated on `EngineerProgress` events |
| `data/session_ledger.json` | Unsold combat/exploration/exobiology value totals for the current session |
| `data/market_destination.json` | The currently pinned Market-tab destination, if any — created on pin, deleted on arrival or manual dismiss |
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

See [LICENSE](LICENSE) for the full license text.
