# Fleet Carrier Materials Finder — Design

## Context

The Engineering panel's Ships and Suits & Weapons tabs each already track a
wishlist of engineering targets and show a "MATERIALS REQUIRED" table plus
an "AVAILABLE FROM — CLOSEST FIRST" engineer-distance table per selected
item. There's no way to know whether a still-missing material is available
from a nearby player-owned Fleet Carrier — a real, common source, since
carriers' "Trade materials" bartender interface buys/sells both ship
materials (Raw/Manufactured/Encoded) and Odyssey microresources
(Data/Goods/Assets) under one mechanism.

## Research

EDDN publishes exactly this data via a schema most consumers don't use:
`fcmaterials_journal/1`, sourced from the game's `FCMaterials.json` file
(signalled by the journal's `FCMaterials` event). Verified directly against
EDCD/EDDN's schema repository (not assumed):

```json
"message": {
  "required": ["timestamp", "event", "MarketID", "CarrierName", "CarrierID", "Items"],
  "Items": [{ "id": int, "Name": "<internal symbol>", "Price": int, "Stock": int, "Demand": int }]
}
```

EDDN strips all `_Localised` fields from this schema, so `Items[].Name` is
always the raw internal material symbol — the same symbol space already
used throughout this codebase (`odyssey_engineering.json`'s requirement
dicts, `settings/odyssey_material_names.json`, the ship Engineering
Wishlist's material keys). No new symbol-mapping work needed to
cross-reference against either wishlist.

**Critical gap, confirmed by reading the schema in full**: this message
carries `MarketID` and `CarrierName`/`CarrierID` but no system name, no
coordinates, nothing locating the carrier. A carrier is a mobile station —
knowing it exists and sells what you need is useless without knowing where
it currently is.

**The fix**: `station_info` (this project's existing table, populated from
`Docked` journal/1 messages — the player's own dockings plus other
commanders' via EDDN, already flowing through `eddn_listener.py`) stores
`market_id -> system_name` and is keyed by `market_id`, the same ID
`fcmaterials_journal` carries. Joining on `market_id` recovers a carrier's
last-known location for free, from data already being collected. This is
inherently a "last known" location, not a live one — a carrier could have
jumped since the docking that produced that `station_info` row. Per an
explicit design decision (see below), a carrier with no matching
`station_info` row is dropped from results rather than shown with an
unknown location.

## Design

### Schema

```sql
CREATE TABLE IF NOT EXISTS fleet_carrier_materials (
    market_id       INTEGER NOT NULL,
    material_symbol TEXT    NOT NULL,
    carrier_name    TEXT,
    carrier_id      TEXT,
    price           INTEGER,
    stock           INTEGER,
    demand          INTEGER,
    last_updated    TEXT NOT NULL,
    PRIMARY KEY (market_id, material_symbol)
);
```

`ON CONFLICT(market_id, material_symbol) DO UPDATE` — one row per
(carrier, material) ever reported, refreshed on each new sighting, matching
the existing `market_prices` table's exact upsert shape.

### EDDN ingestion (mirrors the existing `commodity/3` pipeline)

- **`edc/core/eddn_listener.py`**: add
  `_FCMATERIALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fcmaterials_journal/"`
  as a new branch alongside the existing `_COMMODITY_SCHEMA_PREFIX` check
  (fcmaterials messages have no `event`/journal shape either, same
  reasoning that already gave `commodity/3` its own branch). New signal
  `fcmaterials_seen = pyqtSignal(dict)` emitting the raw message body
  (`MarketID`, `CarrierName`, `CarrierID`, `Items`).
- **`edc/core/eddn_market.py`**: new buffer
  `_fcmaterials_buffer: Dict[Tuple[int, str], tuple]` keyed by
  `(market_id, material_symbol)`, a new `on_fcmaterials_message(msg)`
  method populating it, folded into the existing `pop_buffers()` /
  `write_buffers()` / `flush()` machinery as a sixth buffer type — **never**
  written from the main thread directly; goes through the same background
  `_EddnFlushWorker` every other buffer already uses, per the UI-freeze
  fix already shipped once this session for exactly this failure class.
- **`edc/ui/main_window.py`**: `self._eddn_worker.fcmaterials_seen.connect(self.eddn_market_cache.on_fcmaterials_message)`;
  `_EddnFlushWorker` gains the sixth buffer as a constructor arg, threaded
  through to `write_buffers()`.
- **`persistence/repository.py`**: `save_fleet_carrier_materials_batch(records)`,
  an `executemany` upsert identical in shape to `save_market_snapshot_batch()`.

### Query

`Repository.search_fleet_carrier_materials(material_symbols: list[str], x: float, y: float, z: float, radius_ly: float) -> dict[str, list[dict]]`

Same multi-symbol shape as the existing `search_market_prices_multi()` (one
query for the whole wishlist's missing materials at once, not one query per
item — that per-item version was already found and fixed as a real
performance problem for Trade Opportunities earlier this session, not
repeating it here).

- `INNER JOIN station_info ON station_info.market_id = fleet_carrier_materials.market_id`
  — the "location known only" decision; carriers with no `station_info` row
  never appear.
- Distance filtering reuses the existing `_nearby_system_coords(x, y, z, radius_ly)`
  helper (joins `station_info.system_name` against `system_coords`, same as
  `search_market_prices`'s existing pattern) — a carrier whose last-known
  system also has no harvested coordinates is likewise dropped (same
  precedent as the existing market search, not a new limitation).
- Two independent freshness values are returned per result, both shown in
  the UI rather than collapsed into one: `last_updated` (the material
  listing's own age) and `last_visited` (the location sighting's age, from
  `station_info`) — a carrier could have moved since it was last docked at,
  so the location is explicitly "last known," never asserted as current.
- Cutoff: 7 days on `fleet_carrier_materials.last_updated` (tighter than
  `market_prices`'s existing 30-day cutoff — carriers restock and relocate
  far more often than fixed stations do). No separate cutoff on
  `last_visited`; its age is surfaced to the user as a visible caveat
  instead of silently filtering on it, since a carrier that hasn't moved in
  months is still perfectly findable even if nobody's docked recently.
- Results excluding the currently-docked market (if any) via the same
  `exclude_market_id` parameter convention already used by
  `search_market_prices`.
- Sort: closest first.

### Wishlist scope

Both wishlists get cross-referenced against this same table and query —
the ship Engineering Wishlist (`edc/core/engineering_wishlist.py`,
Raw/Manufactured/Encoded material symbols) and the Odyssey Wishlist
(`edc/core/odyssey_wishlist.py`, on-foot material symbols). Same symbol
space, same query, no schema distinction needed between the two — a
material symbol is either a ship-engineering material or an Odyssey
microresource, never both, so there's no collision risk in sharing one
table.

### UI — `edc/ui/panels/engineering_panel.py`

Both existing wishlist-detail layouts (the Ships tab's class and
`_OdysseyEngineeringTab`) gain a new table, "SOLD BY CARRIERS — CLOSEST
FIRST", placed next to the existing "AVAILABLE FROM — CLOSEST FIRST"
engineer table. Columns: Carrier, System, Dist (ly), Price, Stock, plus a
freshness indicator built from both `last_updated`/`last_visited`.
Refreshes on wishlist-row selection, identical trigger to the existing
`_refresh_engineer_table()` methods — a sibling `_refresh_carrier_table()`
per tab, following the same `self._state.system_x/y/z` reference-position
pattern already used there (not a fresh `system_coords` lookup for the
player's own position — that data is already directly on `state`).

Radius reuses the existing `cfg.market_search_radius_ly` setting (same "how
far I'll travel" semantics already governing the Market and Trade Route
panels) — no new config value.

## Testing

- Ingestion parsing (`on_fcmaterials_message`) and the search query are
  fully synthetic-testable against a real temp-file SQLite DB: insert known
  `fleet_carrier_materials` + `station_info` + `system_coords` rows,
  confirm distance filtering, the 7-day cutoff, the INNER JOIN's
  location-unknown exclusion, and the `exclude_market_id` behavior.
- Live EDDN verification the same way `eddn_market.py`'s other buffers were
  verified earlier this session — run it, confirm real `fcmaterials_journal`
  messages arrive, parse, and land in `fleet_carrier_materials` within a
  short observation window. No in-game session required, since this is
  galaxy-wide data from all commanders' carriers.
- UI wiring (the new table appearing and populating correctly in both tabs)
  confirmed visually, matching this project's established convention for
  UI-layer changes.
