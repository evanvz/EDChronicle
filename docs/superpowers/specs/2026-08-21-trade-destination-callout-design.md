# Trade Destination Opportunity Callout — Design

## Context

EDChronicle already has almost everything this feature needs, built for a
different trigger (manual search, not automatic-on-arrival):

- **`edc/core/trade_routes.py::find_point_to_point_trades(origin_items, destination_stations, cargo_capacity, max_results)`**
  — pure, already-tested profit engine. For every commodity buyable at the
  origin, finds the best-selling destination station, caps quantity by
  `min(cargo_capacity, stock, demand)`, excludes non-positive-margin
  entirely, returns sorted by total profit descending (ties broken by data
  freshness). This is reused as-is — no changes to its logic or signature.
- **`edc/ui/panels/trade_route_panel.py`**'s existing Point-to-Point Trade
  Finder section: a destination-system text field (`_dest_edit`, already
  auto-filled from `state.route_destination_system` — the game's own
  plotted nav-route target — when the user hasn't typed their own), a
  manual "Search" button, and a results table. Its origin items come
  exclusively from `state.current_market_items`, which is only ever
  populated by `_load_current_market()` reading `Market.json` — a file the
  game only writes once the in-game Commodities screen is opened. There is
  no cached/last-known fallback today.
- **`Repository.get_market_snapshot_for_systems([system_name])`** — fetches
  every known station in a system for the P2P search; no pad-size filter,
  no single-station narrowing (the Trade Route Loop Planner has its own
  separate pad-filter combo, unrelated to this P2P section).
- **`state.cargo_capacity`** — total ship cargo capacity from `Loadout`, NOT
  remaining free space. `state.cargo_inventory` (already tracked, backs the
  existing "In Cargo — Sell At" feature) holds what's currently loaded.
  Remaining space = `cargo_capacity - sum(item quantities in cargo_inventory)`
  — this feature is the first caller that needs the *remaining* figure, not
  raw capacity.

What's missing, confirmed by direct code read (not assumed): automatic
triggering on arrival, a way to say "auto-check this destination on
arrival" that survives a restart, a cached-market fallback for before the
Commodities screen is opened, pad-size filtering in the P2P path, a
minimum-cargo-space floor, and a voice callout.

## Design

### 1. Destination store — `edc/core/trade_destination.py`

New `TradeDestinationStore`, mirroring `MarketDestinationStore`'s exact
shape (`persistence file: data/trade_destination.json`):

```python
{"system_name": str, "station_name": str,  # "" means "whole system"
 "set_at": iso timestamp}
```

Separate from `MarketDestinationStore` (confirmed with user: kept
independent, not merged) — that one stays the single-commodity
search-result pin it already is.

### 2. Setting the destination — UI

Add a small control next to the existing P2P destination field on the
Trade Route panel: a "Auto-check on arrival" checkbox/button. Checking it
saves the current `_dest_edit` text (system name) plus an optional station
name (new small combo box, populated from `get_market_snapshot_for_systems`
once a system is entered — blank/"Any station" selectable) into
`TradeDestinationStore`. This reuses the existing destination-entry field
rather than building a second one — the only new UI is the checkbox +
station combo.

### 3. Two-tier origin data

**New repository method** `get_market_snapshot_for_market_id(market_id) ->
list[dict]`, same item shape as `current_market_items` (name/symbol/
buy_price/sell_price/demand/stock), sourced from `market_prices` filtered
to that one `market_id` — this is the tier-a cached fallback.

- **Tier a (docked, Commodities screen not yet opened):** on `Docked`,
  `state.current_market_items` is still empty. Build origin items instead
  via the new repo method, keyed by the `MarketID` the `Docked` event
  itself already carries.
- **Tier b (Commodities screen opened):** `state.current_market_items` is
  populated as it already is today; use it directly, exactly like the
  existing manual P2P search does.

### 4. Remaining cargo + minimum floor

New helper (pure function, e.g. in `trade_routes.py` or `state.py`):
`remaining_cargo_space(capacity: int, inventory: list[dict]) -> int` =
`capacity - sum(item quantities)`, floored at 0.

New config field `AppConfig.min_trade_callout_cargo: int = 8` (same
pattern as `min_planet_value_100k`), with a Settings spinbox. If remaining
space is below this floor, skip the check entirely — no query, no
callout, matches "one spot open, don't bother."

### 5. Trigger flow

**On `Docked`:** if a destination is saved in `TradeDestinationStore`:
1. Compute remaining cargo space; if below the floor, stop (silent).
2. Build tier-a origin items for the current station.
3. Fetch destination stations (`get_market_snapshot_for_systems`), filtered
   to the saved station name if one was set, else all stations in that
   system filtered by the current ship's landing pad size (new filter
   parameter threaded into the destination-station fetch — reusing the
   same pad-size logic the Loop Planner's combo already applies elsewhere,
   applied here unconditionally against the ship's actual current pad
   requirement, not a user-chosen minimum).
4. Call `find_point_to_point_trades(origin_items, destination_stations,
   remaining_space, max_results=1)`.
5. If a result exists, speak it (see below) and remember it as the "last
   announced" result for this docking. If not (no data for destination, or
   no positive-margin trade), stay silent.

**On `Market` event (Commodities screen opened), same destination still
set:** repeat steps 2-4 using tier-b live items. Compare the new best
result to the "last announced" one (by commodity + total profit) — speak
again only if it changed; otherwise stay silent (confirmed with user:
silent re-check, not a duplicate announcement, not "once only" either).

### 6. Voice callout

New `edc/audio/handlers/trade.py`, `TradePhrases` class, following the
established phrase-pool + `pick()` pattern (no-repeat already built into
`pick()`). Example shape: `"{commodity} sells well at {station} in
{system} — {quantity} units, {profit} credits profit."` — exact wording
finalized during implementation, matching this session's established
"personal crew-voice tone" pass over every other phrase pool.

## Out of scope

- No change to `find_point_to_point_trades()`'s logic, `MarketDestinationStore`,
  or the Trade Route Loop Planner's own round-trip search.
- No multi-leg/loop logic here — single buy-here-sell-there leg only,
  matching what was asked for.
- No live external network lookup for an unknown destination system — per
  confirmed understanding, this stays a pure local DB query; a destination
  system EDChronicle has never seen at all simply yields no data (silent),
  same as any other "no data" case.
