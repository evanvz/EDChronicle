# Trade Route Loop Planner — Design

## Context

Inspired by Inara's "Trade Routes" screen: an A→B→A round trip where you
buy commodity X cheap at A and sell it high at B, then buy a *different*
commodity Y cheap at B and sell it back at A — profit on both legs of one
physical loop, not a one-directional buy/sell like Market's existing
search and Trade Opportunities.

Everything needed already exists in this codebase — this is a new
computation and a new tab, not a new data source:
- `market_prices` (galaxy-wide EDDN commodity feed, buy/sell/demand/stock
  per station) and `_nearby_system_coords()`'s radius bounding-box
  pre-filter (`persistence/repository.py`).
- `EdsmPowerPlayCache.get_controller_by_name()` (today's enemy-PowerPlay
  exclusion work) for the PowerPlay filter.
- `find_faction_stations_in_system`-style logic (Player Faction tab) for
  the faction filter.
- The `BusySpinner` + QThread-worker pattern used by every search in
  Market/Mining/PowerPlay Target Finder today.

Decided in discussion:
- **A→B→A round trips only** — not open multi-leg pathfinding. Matches
  the Inara screenshot exactly and keeps the search a bounded pairing
  problem instead of combinatorial route search.
- **Anchored to current location + radius**, same pattern as every other
  search in this app (no arbitrary-origin override for v1).
- **New sidebar tab** ("Trade Routes"), not a card grafted onto Market —
  its own radius/filter controls, not shared state with Market's.
- **Cargo capacity auto-read only**, from the journal's `Loadout` event's
  `CargoCapacity` field (fires on every ship swap/dock/module change,
  always reflects the ship currently being flown) — no manual entry or
  override.
- **Two independent filter checkboxes**: "Exclude enemy PowerPlay
  systems" (identical rule to Market's) and "Only my squadron faction's
  controlled stations" — toggle either, both, or neither.
- **Manual search only** (a Search button), no auto-refresh-on-dock like
  Trade Opportunities — this is a heavier computation than any existing
  search, so it never runs unless explicitly requested.

## Data flow / algorithm

1. **Bound the candidate set.** Reuse `_nearby_system_coords(x, y, z,
   radius_ly)` to get every system within radius — identical first step
   to every existing search.
2. **One batched query, not per-commodity.** New repository method
   `get_market_snapshot_in_radius(x, y, z, radius_ly)` returns every
   `(market_id, commodity_name, buy_price, sell_price, demand, stock,
   station_name, system_name, pad info)` row for stations in that bounded
   set, in a single query (mirrors `search_market_prices_multi`'s "one
   query beats N" fix from Trade Opportunities) — no per-commodity
   looping, no per-station-pair querying.
3. **Group in Python**, not SQL: `{market_id: {"sells": {commodity:
   (sell_price, demand)}, "buys": {commodity: (buy_price, stock)},
   station_name, system_name, coords, pad_size}}`. A bounded radius
   (matching Market's existing 10-5000 ly range) keeps this to at most a
   few thousand stations — small enough to hold in memory and iterate in
   pure Python without another SQL round-trip.
4. **Find round trips.** For each ordered station pair (A, B) with A ≠ B:
   - Leg 1: commodities A sells that B buys — profit/unit = B.buy_price −
     A.sell_price, keep the best one.
   - Leg 2: commodities B sells that A buys — same, independently.
   - A pair only qualifies if **both** legs are profitable (a one-way-only
     pair isn't a loop). Total round-trip profit = (leg1 profit/unit +
     leg2 profit/unit) × cargo capacity, capped by each leg's own
     `demand`/`stock` where lower than capacity (can't sell/buy more than
     the market has, per the 25%-of-demand tapering warning already
     shipped today — this reuses the same "cap at 25% of demand for the
     *reliable* portion" framing, not a hard cutoff).
   - This is the O(N²) part, but bounded: N is "stations within radius,"
     not "stations in the galaxy," and per-pair work is a dict lookup
     against each station's (small) commodity list, not another query.
     A hard cap (e.g. radius default 50 ly, same ballpark as Market's
     100 ly default but tighter since this is O(N²) not O(N)) plus a
     result-count cap (top 50 loops by total profit) keeps worst-case
     bounded regardless of how busy the region is.
5. **Apply filters** (enemy-PowerPlay exclusion, faction-controlled-only)
   to the candidate station list *before* step 4's pairing — fewer
   stations means less pairing work, not just fewer results shown.
6. **All of the above runs in a background QThread worker** with its own
   DB connection (project's cross-thread SQLite rule), identical shape to
   `_TradeOpportunityWorker`/`_MarketSearchWorker`, with the `BusySpinner`
   shown over the results table while it runs.

## UI

New `edc/ui/panels/trade_route_panel.py`, new sidebar tab "Trade Routes":
- Radius spinbox (default 50 ly, range 10-500 — capped lower than
  Market's 5000 ly ceiling given the O(N²) cost).
- The two filter checkboxes.
- Cargo capacity shown read-only (e.g. "Cargo: 216t (from current ship)")
  — sourced from `state.cargo_capacity`, a new field set from `Loadout`'s
  `CargoCapacity` in `event_engine.py`, mirroring how `ship_has_weapons`
  is already set from the same event.
- Search button + `BusySpinner`.
- Results table: Station A, Station B, distance between them, Leg 1
  (commodity, profit/unit), Leg 2 (commodity, profit/unit), **Total
  round-trip profit** (the hero number — leg profits × cargo capacity),
  sorted by that descending. Click a station cell to copy its name
  (existing convention throughout this app).

## Out of scope

- Open multi-leg routes (A→B→C→...) — explicitly deferred, real
  pathfinding is a different, larger problem.
- Arbitrary-origin search (planning from somewhere you aren't) — v1 is
  current-location-only, matching every other search in this app.
- Manual cargo capacity override — auto-read only per discussion.
- Auto-refresh/re-trigger on docking — manual search only, given this is
  the heaviest computation of any search feature in the app so far.
