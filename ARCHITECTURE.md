# EDChronicle — Architecture & Internals

Technical deep-dive for contributors. For what the app does and how to install/run it, see [README.md](README.md).

## Data sources & ecosystem contribution

EDChronicle draws on the same community data network the rest of the Elite Dangerous tooling ecosystem uses:

- **[Spansh](https://spansh.co.uk)** — body enrichment, PowerPlay system search, ring/hotspot mining search, ring hotspot community-data gaps
- **[EDSM](https://www.edsm.net)** — daily PowerPlay dump (independent cross-check against Spansh), and per-system faction lookups for Player Faction CSV import
- **[EDDN](https://github.com/EDCD/EDDN)** — live subscription for real-time PowerPlay cross-checking, network-wide squadron faction presence tracking, the galaxy-wide commodity price feed behind the Market tab, and station services/pad sizes crowdsourced from every commander's dockings (the same model Inara/EDSM use) — the same feed Spansh and EDSM themselves are built from
- **[Canonn](https://canonn.tech)** — community-sourced Codex/POI intel for the current system and nearest unclaimed Codex challenge
- **[Inara](https://inara.cz)** — optional bulk CSV export of a minor faction's full system presence list, for the Player Faction tab's bulk import

EDChronicle can also contribute back: "Contribute data to EDDN" in Settings (on by default, matching EDMarketConnector's own default — turn it off if you'd rather not) publishes a subset of your journal events (jumps, docking, scans, surface signal scans, carrier jumps, codex entries) to EDDN's `journal/1` schema, your own market visits (commodity buy/sell prices, stock, demand — including your own Fleet Carrier's docking access, when applicable) to EDDN's `commodity/3` schema whenever you open a station's Commodities screen, and your own Fleet Carrier's material listings to EDDN's `fcmaterials_journal/1` schema whenever you open its bartender screen — the same feeds the Market tab's search and the Engineering tab's "Sold by Carriers" search draw from. All of this benefits every tool that consumes EDDN, not just EDChronicle. No personal data beyond your commander name is included, and EDDN obfuscates that before distributing it further.

Engineering blueprint costs, Experimental Effect data, Odyssey grade/module recipes, and the Material Trader's trade ratios are static offline reference data sourced from [EDCD/coriolis-data](https://github.com/EDCD/coriolis-data), [EDCD/FDevIDs](https://github.com/EDCD/FDevIDs), [msarilar/EDEngineer](https://github.com/msarilar/EDEngineer), and [jixxed/ed-odyssey-materials-helper](https://github.com/jixxed/ed-odyssey-materials-helper) — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the MIT-licensed portions' full attribution.

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
2. `edc/core/edsm_powerplay.py` refreshes a daily-cached EDSM PowerPlay dump on startup (a plain request with an identifying User-Agent — EDSM's Cloudflare front-end 403s the default python-requests UA, not the request itself)
3. `edc/ui/panels/powerplay_finder_panel.py` cross-checks each Spansh search result's controlling power against both sources and flags disagreement
4. `eddn_market.py` buffers commodity prices, station sightings, Fleet Carrier material listings, carrier docking access, and squadron-faction sightings in memory and flushes to SQLite periodically in one batched transaction (`Database.deferred_commit()`), rather than committing per message
5. On every raw journal event, `MainWindow` calls `edc/core/eddn_publisher.py::observe()` to track session header fields (commander, game version, Horizons/Odyssey flags); if "Contribute data to EDDN" is enabled in Settings, `maybe_publish()` builds a schema-compliant `journal/1` message and queues it for background delivery to the EDDN gateway
6. On the `Market` event, `_load_current_market()`'s already-parsed `Market.json` dict is also handed to `maybe_publish_commodity()`, which builds a `commodity/3` message (applying EDDN's required elisions/renames, plus your own carrier's docking access when the market is confirmed your own) and queues it on the same gateway worker — same opt-in setting, no separate toggle
7. On the `FCMaterials` event, `_load_current_fcmaterials()` reads `FCMaterials.json` and hands it to `maybe_publish_fcmaterials()`, which builds an `fcmaterials_journal/1` message and queues it the same way

### 5. Player Faction (BGS) tracking path

Builds and maintains the full system-presence list for your squadron-aligned minor faction, and the bucket dashboard built on top of it.

Flow:

1. `edc/core/squadron_scanner.py` scans full journal history at startup to detect the squadron-aligned faction and any already-known presence
2. Live `Docked`/`FSDJump`/`Location` events save a faction snapshot for the current system (`faction_snapshots` table) via `MainWindow._save_faction_snapshots()`, and `MainWindow.update_reference_state()` pushes the current position to the panel on every event (cheap — just a reference update, not a rebuild) so distance calculations stay correct even without the tab open
3. The EDDN network-wide listener (path 4) supplies presence data for systems never personally visited
4. `edc/core/edsm_faction_lookup.py` + `edc/core/inara_faction_csv.py` support manual add and bulk CSV import, resolving each system live against EDSM with retry-on-block; a `_FactionRefreshWorker` re-queries every tracked system once per local calendar day (so a fresh day's first session always gets one, matching the BGS's own daily tick — not a rolling 24h window) and backfills `system_coords` via `fetch_system_coords()`
5. `edc/ui/panels/player_faction_panel.py` classifies every system into 0+ status buckets (`_compute_buckets()`, pure in-memory, no extra queries) and renders them as tiles; clicking one opens a `_FactionBucketDialog` (non-modal `QDialog`, kept alive in a dict so it survives tab switches) which re-renders live as buckets are recomputed on arrival or after a manual recheck

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
- `edsm_faction_lookup.py` — per-system faction lookup (with retry on transient failures) for Player Faction add/import
- `eddn_listener.py` / `eddn_powerplay.py` — live EDDN PowerPlay subscription
- `eddn_market.py` — buffered EDDN commodity price, station, Fleet Carrier material listing, carrier docking access, and squadron faction sighting ingestion
- `eddn_publisher.py` — opt-in `journal/1` (jumps, docking, scans...), `commodity/3` (market visits, including your own carrier's docking access), and `fcmaterials_journal/1` (your own carrier's material listings) publishing back to EDDN
- `canonn_client.py` — Canonn Codex/POI community intel
- `inara_faction_csv.py` — parses Inara's faction-presence CSV export format
- `bgs_conflicts.py` — squadron-aligned faction lookup, finds who it's at active war with in the current system, and backs BGS activity attribution (bounty/trade crediting)
- `ship_loadout.py` — classifies current ship hardpoints as armed/unarmed from `Loadout` events
- `faction_refresh_tracker.py` — persists the last full-EDSM-refresh timestamp for the Player Faction tab's 24h auto-refresh gate
- `rank_names.py` — Rank/Progress category index → real rank name tables (Elite I-V aware), verified against the community Journal Manual
- `rank_scanner.py` — full-journal-history scan for the most recent Rank/Progress values at startup (same reasoning as `notoriety_scanner.py`)
- `bounty_scanner.py` / `notoriety_scanner.py` / `squadron_scanner.py` / `carrier_scanner.py` / `mission_scanner.py` / `combat_bond_scanner.py` / `materials_scanner.py` — full-journal-history scanners that reconstruct current state at startup (bounties, notoriety, squadron, fleet carrier, active missions, unredeemed combat bonds, held materials). The five that have no periodic snapshot event to jump to (bounties, combat bonds, squadron, carrier, missions) run on a background thread (`_StartupHistoryScanWorker` in `main_window.py`) so a long journal history doesn't block the window from appearing
- `trade_routes.py` — pure A↔B↔A trade-loop-finding logic for the Trade Route Loop Planner
- `material_trading.py` — Material Trader up/down-trade suggestion logic and material grouping/grade data
- `experimental_effects.py` — Experimental Effect material costs and blueprint/weapon-type compatibility
- `odyssey_material_source.py` — Bartender-tradeable vs farm/loot-only classification for Odyssey materials
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
- `trade_route_panel.py`
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
| `station_info` | Landing pad counts, station services, and (for Fleet Carriers) self-reported docking access — from `Docked` events, yours and every commander's via EDDN |
| `market_prices` | Galaxy-wide commodity prices from the EDDN commodity feed, keyed by market + commodity |
| `system_bgs_status` | Latest known War/CivilWar conflicts and multi-state factions per system, from journal visits and EDDN — one row per system, not daily history |
| `system_res_sites` | Latest known RES/Low RES/High RES/Hazardous RES tier presence per system, from journal visits and EDDN |
| `fleet_carrier_materials` | Galaxy-wide Fleet Carrier engineering material listings from EDDN, keyed by market + material |
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
| `settings/experimental_effects.json` | Experimental Effect material costs, blueprint-category and weapon-type compatibility (reference data, not user-specific) |
| `settings/engineer_requirements.json` | Per-engineer discover/meet/unlock/referral requirement text for the Engineers reference tab (reference data, not user-specific) |
| `settings/voice_commands.json` | Ship command bindings, tab-navigation trigger word, input/output audio device, feedback volume |
| `data/engineering_wishlist.json` | User-selected blueprint/grade build targets, each with an optional Experimental Effect and (for weapons) hardpoint type |
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
