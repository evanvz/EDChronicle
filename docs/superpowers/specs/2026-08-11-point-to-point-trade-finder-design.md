# Point-to-Point Trade Finder — Design

## Context

The existing Trade Route Loop Planner auto-discovers round-trip loops
via nearest-neighbor search within a radius. Requested: a one-way
finder — given the station EDChronicle is currently docked at (origin)
and a specific destination (typed manually, or auto-detected from the
game's currently plotted route), find what to buy at the origin and
sell at the destination for the best profit.

## Research

**Destination auto-detection needs zero new journal parsing.**
`FSDTarget` is already handled in `event_engine.py:462-475`, populating
`state.route_target_system`/`route_remaining_jumps`; `NavRouteClear`
already resets both. This is the final destination of a plotted route
(the payload's `RemainingJumpsInRoute` field only makes sense in that
context, not a single next-hop target).

**Origin data should come from live state, not the DB.** The Loop
Planner's `get_market_snapshot_in_radius()` sources everything from
`market_prices` (EDDN-fed), but for the *current* station specifically,
`state.current_market_items` (already parsed into memory the moment
the commodities screen is opened — see `main_window.py::_load_current_market()`)
is more reliable: it doesn't depend on our own outbound EDDN publish
being picked back up by our own inbound listener, which is a separate,
unordered round trip with no freshness guarantee. Zero new query needed
for the origin side.

**Destination needs one new, narrow repository method.** The existing
`get_market_snapshot_in_radius(x, y, z, radius_ly)` does a radius+distance
search — the wrong shape for "exactly this one system." A same-shaped
variant filtered by exact system name(s) instead is a small, direct
adaptation (confirmed by reading the existing method fully:
`persistence/repository.py:1349-1420`).

**The profit math already exists and is proven.** `trade_routes.py::_best_leg()`
computes `profit_per_unit = sell_price - buy_price`, caps quantity at
`min(cargo_capacity, stock, demand)`, and tracks the older of the two
sides' `last_updated` as the effective data age — exactly the math this
feature needs. `_best_leg()` itself only returns the single best
commodity for one buy/sell station pair; this feature needs the same
formula extended to rank *every* profitable commodity, across
potentially several stations in the destination system, so it's a new
function reusing the formula rather than a call to the existing one.

**Commodity-name matching is a solved problem already.** `market_prices.commodity_name`
stores normalized symbols (`"lowtemperaturediamonds"`, no spaces/case);
`state.current_market_items`'s `"name"` field is the display form
(`"Low Temperature Diamonds"`). `normalize_commodity_name()`
(`market_panel.py:43-49`) already bridges exactly this gap for free-text
search there — reused here for the same reason, not reimplemented.

**Cargo capacity** is already tracked at `state.cargo_capacity`
(`state.py:36`), populated and consumed by the Loop Planner exactly the
way this feature needs it.

## Design

**`persistence/repository.py`** — new method:

```python
def get_market_snapshot_for_systems(self, system_names: list[str]) -> dict[int, dict]:
    """Same shape as get_market_snapshot_in_radius() -- {market_id: {
    "station_name", "system_name", "pad_size", "controlling_faction",
    "sells": {commodity: (sell_price, demand, last_updated)},
    "buys": {commodity: (buy_price, stock, last_updated)}}} -- but
    filtered to an exact list of system names instead of radius+distance.
    No coords/distance needed since there's no radius to check against."""
```

Query body is the existing method's query with the radius/distance
filtering removed and `system_name IN (...)` substituted directly —
same row-shaping loop, same `station_info` join for pad size, same
`_market_data_cutoff()` staleness filter, same Fleet-Carrier exclusion.

**`edc/core/trade_routes.py`** — new function:

```python
def find_point_to_point_trades(
    origin_items: list[dict],       # state.current_market_items shape
    destination_stations: dict[int, dict],  # from get_market_snapshot_for_systems
    cargo_capacity: int,
    max_results: int = 10,
) -> list[dict]:
    """For every commodity buyable at the origin, finds the best-selling
    destination station for it (if the destination system has more than
    one) and computes a cargo-capacity-capped total profit. Same profit/
    capping formula as _best_leg(), extended across every commodity and
    every destination station instead of returning only the single best
    pairing. Returns up to max_results, sorted by total profit
    descending; commodities with no positive-margin destination are
    excluded entirely, not returned as zero/negative rows."""
```

Each origin item's display `"name"` is normalized via
`normalize_commodity_name()` before matching against
`destination_stations[...]["sells"]` keys (which are already stored
normalized).

Each result: `{commodity, sell_station_name, sell_system_name, buy_price,
sell_price, profit_per_unit, quantity, total_profit, data_age_hours}`.

**`edc/ui/panels/trade_route_panel.py`** — new "Point to Point" section,
following the existing Loop Planner section's card/table conventions in
the same file:

- A destination `QLineEdit`, auto-filled from `state.route_target_system`
  whenever it's set and the user hasn't manually edited the field this
  session (same "auto-populate but stay editable" pattern as the
  existing cargo-capacity label), cleared when `route_target_system`
  clears.
- A Search button, disabled when the destination field is empty or
  `state.cargo_capacity` is unknown (mirrors the Loop Planner's existing
  disabled-state logic).
- A results table: Commodity, Sell Station, Buy Price, Sell Price,
  Profit/Unit, Quantity, Total Profit, Data Age — same column
  conventions (numeric sort via the existing `_NumericTableWidgetItem`,
  data-age color/text via `fmt.relative_time()`) as the Loop Planner's
  own results table in the same file.
- Empty states: "No market data for `<system>` yet" if
  `get_market_snapshot_for_systems([...])` returns nothing for that
  system; "No profitable trades found" (not styled as an error) if
  `find_point_to_point_trades()` returns an empty list for a system that
  *does* have market data.

## Testing

- `find_point_to_point_trades()`: synthetic tests mirroring
  `test_trade_routes.py`'s existing pattern — fake `origin_items` list
  and a fake `destination_stations` dict. Cases: capacity capping
  (profit caps at `cargo_capacity` even when stock/demand allow more);
  negative-margin commodities excluded; best-station-per-commodity
  selection when the destination system has two stations both selling
  the same commodity at different prices; `max_results` truncation;
  commodity-name normalization actually matches origin's display name
  against destination's stored symbol.
- No test for `get_market_snapshot_for_systems()` or the UI wiring —
  consistent with this codebase's existing convention (the sibling
  `get_market_snapshot_in_radius()` has no dedicated test either, and no
  panel file has UI tests anywhere in this repo).
