# Hub-first market search — design

Date: 2026-10-28. Repos: EDDataHub (`C:\Dev\EDDataHub`, server 172.16.10.197) and EDChronicle (`C:\Dev\EDChronicle`).

## Intent

EDChronicle keeps a galaxy-wide local market table (`net.market_prices`, ~13.8M rows, 3.5 GB `network_cache.db`) fed from EDDataHub's EDDN relay. Searches against it take several seconds each and the table drives prune jobs, index builds and WAL-lock workarounds. EDDataHub runs Postgres on a LAN server with ~434 GB free disk and already receives every `commodity/3` message, but only archives it to disk (30 days of raw gz files); it stores no market table.

Goal: when EDDataHub is reachable, the app's market searches are answered by the hub. When it is not, the app answers from its local table exactly as it does today.

## Decisions (Evan, 2026-10-28)

- Searches go to the hub first; the local table is the fallback.
- The local table keeps filling from the hub relay as it does now, so the fallback is always warm. No change to local ingestion.
- Local prune stays 21 days (`_MARKET_DATA_MAX_AGE_DAYS = 21`, `prune_stale_market_prices`).
- The hub keeps only the latest price per station and commodity: no price history.
- The hub's market rows are pruned at 21 days, same as the app.
- The trade-route single-station lookup (`edc/ui/panels/trade_route_panel.py:197`, demand bracket by `market_id`) stays local.
- The app does not show where search results came from (no "EDDataHub"/"local" label).
- Direct EDDN stays opt-in, off by default (`eddn_direct_fallback`, commit 4d49341). The app never reads EDDN directly unless that is turned on.

## Non-goals

- Price history, price charts, trends.
- Fleet carrier materials (`fcmaterials`) on the hub — `search_fleet_carrier_materials` stays local.
- Changing local ingestion, the local schema, or local pruning.
- Any UI change.
- Exposing the hub's market data to anyone outside the LAN or to third parties.

## Anti-goals

- Searches must never get slower or fail because the hub is down or slow: a hub problem falls back silently to today's local query.
- Results from the hub must not differ in shape or filtering from local results; the panels must not need to know the source. (Content can differ slightly where the two stores differ; see My calls.)

## EDDataHub side

### Storage

New table (next migration number in `sql/`), one row per station × commodity, latest wins:

- `market_id` bigint, `commodity` text (EDDN `name` as sent, e.g. `platinum` — the app stores the same raw name), PK (`market_id`, `commodity`)
- `station_name`, `station_type`, `system_name` text
- `sell_price`, `buy_price`, `mean_price`, `demand`, `demand_bracket`, `stock`, `stock_bracket` integer
- `updated_at` timestamptz (message `timestamp`)

A newer message for a station replaces that station's rows: commodities absent from the new snapshot are removed for that `market_id` (a market snapshot is the whole market). Older-than-stored messages are ignored. Messages more than 10 minutes in the future are dropped (same rule as the rest of the hub, `MAX_FUTURE`).

Note: `eddatahub/parse.py` currently says markets are "never stored as facts" and scope is PowerPlay + BGS. This design deliberately widens scope to markets; update that comment. Markets do not go into `observation_latest`/`current_facts`; they get their own table.

### Feed

- Live: the EDDN listener (`eddatahub/eddn.py`) already receives and archives `commodity/3`. Write each one to the new table too, via the existing writer thread so a slow DB never blocks receiving.
- Backfill: one-off command that replays the last 21 days of `commodity/3` from the raw archive into the table (oldest to newest, or newest-first skipping stations already written — builder's choice). `latest_markets()` in `eddn.py` already walks the archive this way.
- Prune: delete rows with `updated_at` older than 21 days, from the existing maintenance job (`eddatahub/maintain.py`).

### Search endpoint

`GET /api/market-search` on the existing web server (`eddatahub/web.py`).

Parameters:
- `commodity` — one or more names (repeatable or comma-separated; builder's choice, but must serve `search_market_prices_multi` in one request)
- `x`, `y`, `z` — reference position (float)
- `radius` — ly (float)
- `exclude` — optional `market_id` to leave out

Returns, per row: `market_id`, `commodity`, `station_name`, `station_type`, `system_name`, `sell_price`, `demand`, `stock`, `last_updated` (ISO `YYYY-MM-DDTHH:MM:SSZ`, same format the app uses), `x`, `y`, `z`, `distance_ly`, and the landing pads `pads_small`, `pads_medium`, `pads_large` when the hub's `station` facts (from `Docked`, `LandingPads`) know them, else null.

Filters, identical to the app's local query (`persistence/repository.py` `search_market_prices`):
- `sell_price` not null
- not a fleet carrier: `station_type != 'FleetCarrier'` and station name not a carrier callsign (`[A-Z0-9]{3}-[A-Z0-9]{3}`)
- `updated_at` within 21 days
- within `radius` of (x, y, z), true distance, not just the box

Positions: join `system_name` to the hub's system coordinates (`current_facts` `system` facts carry `StarSystem` + `StarPos`; `region_systems` also has name + x/y/z). Stations with no known position are left out, as the local query does (INNER JOIN on `system_coords`).

Needs an index that makes "commodity within a box" fast on a spinning disk.

LAN-only, read-only, same access rules as the existing `/api/*` routes. Input validated (numbers finite, radius capped, commodity count capped).

## EDChronicle side

- `edc/core/eddatahub_client.py`: `fetch_market_search(base_url, commodities, x, y, z, radius, exclude_market_id)` → rows, or `None` on any failure (unreachable, timeout, bad status, bad JSON). Same pattern as the other `fetch_*` functions.
- `persistence/repository.py` `search_market_prices` and `search_market_prices_multi`: when `eddatahub_url` is set, call the hub first. If it returns rows (including an empty list), post-process them exactly as local rows are (pad size via `effective_pad_size`, sort known-pad first then best sell price, group by commodity for `_multi`) and return. If it returns `None`, run today's local query unchanged.
- Callers (market panel, mining panel, trade opportunities) do not change. They already run these searches in worker threads.
- No hub URL set (public install): behaviour unchanged.

## Left to the builder

- Migration number, table and index names.
- Backfill order and batching.
- Whether the repository or the client does the hub-vs-local switch, provided callers stay unchanged.
- How the repository gets the hub URL (config is already read elsewhere for `fetch_markets`).

## My calls (not discussed with Evan)

- **Readiness:** `/api/market-search` answers 503 until the backfill has completed once (a state row the backfill sets). The app treats any non-200 as "hub unavailable" and falls back to local. After that, an empty hub result is a real answer, not a reason to fall back.
- **Hub slow or down:** after a hub search failure the app skips the hub for 60 s and goes straight to local, so a dead or slow hub costs one timeout per minute, not one per search. The search timeout is short (3 s), not the client's 8 s `_TIMEOUT`.
- **Own docked market:** no local overlay on hub results. `eddn_contribute_enabled` is on by default, so the player's own `Market.json` reaches EDDN and the hub within seconds. Accepted: a search in the first seconds after docking may show the hub's older copy of that station.
- **Pads:** hub returns pads from its `station` facts. Where the hub's pads are null, the app fills them from local `net.station_info` by `market_id` before `effective_pad_size`, so known-pad ranking matches local as closely as possible.
- **Fleet carrier filter on the hub:** exclude when the market row's `station_type` or the hub `station` fact's `StationType` is `FleetCarrier`, or the name is a callsign (mirrors local, which checks both `m.station_type` and `si.station_type`).
- **`station_faction`:** hub returns it from `station` facts when known, else null; same key as local single-commodity results.
- **Positions:** hub `current_facts` `system` `StarPos` first, `region_systems` second. Before cutover, the builder checks on the server how many stations in the market table have no position (log a count); stations without a position are left out, as local does.
- **Snapshot replace:** the hub replaces a station's whole commodity list on each snapshot; local keeps upserting and may keep commodities a station no longer lists. The hub is the more accurate of the two; the small difference is accepted.
- Spec lives in EDChronicle's docs because the prior cross-repo spec (PP week history) did.

## Deploy

Hub change goes live only after Evan runs `sudo bash /opt/eddatahub/app/deploy/update.sh` and the backfill command on the server. The app falls back to local until then.
