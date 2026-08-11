# EDDN Commodity Publishing — Design

## Context

EDChronicle's Trade Route Loop Planner and Market panel are built entirely
on other commanders' `commodity/3` contributions to EDDN (`eddn_market.py`
consumes the live feed). We never contribute our own market visits back —
`edc/core/eddn_publisher.py` only publishes the `journal/1` schema
(Docked, FSDJump, Scan, Location, SAASignalsFound, CarrierJump,
CodexEntry). Flagged while reviewing what EDDN schemas exist and comparing
against what we send; approved to build.

## Research

Confirmed against a real `Market.json` on the user's own machine (not just
the schema doc) that every field EDDN's `commodity-v3.0.json` requires is
already present in the game's own file:

```
top level: timestamp, event, MarketID, StationName, StationType, StarSystem, Items
per item:  id, Name, Name_Localised, Category, Category_Localised,
           BuyPrice, SellPrice, MeanPrice, StockBracket, DemandBracket,
           Stock, Demand, Consumer, Producer, Rare
```

`commodity-v3.0.json`'s `commodities[]` requires exactly: `name`,
`meanPrice`, `buyPrice`, `stock`, `stockBracket`, `sellPrice`, `demand`,
`demandBracket` — a 1:1 rename of the Market.json fields above (`Name`→
`name`, `BuyPrice`→`buyPrice`, etc.), all present already.

EDDN's own `commodity-README.md` documents the exact required elisions
when sourcing from the journal folder (not CAPI):

- Drop `StationType` at the message level.
- Drop `Producer`, `Rare`, `id`, `Category`/`Category_Localised` from each
  item.
- Strip the `$` prefix and `_name;` suffix from `Name` (e.g.
  `$platinum_name;` → `platinum`).
- Skip items with `Category` = `NonMarketable` (Limpets) or a non-empty
  `legality` value, before the `Category` key is stripped.
- Omit `economies`/`prohibited` entirely (journal data has neither) — the
  schema forbids sending empty lists for them.
- Must set `gameversion`/`gamebuild`/`horizons`/`odyssey`, same as the
  existing journal publisher already tracks via `observe()`.

No EDDN guidance found anywhere against submitting Fleet Carrier markets —
the schema has a dedicated optional `carrierDockingAccess` field for
exactly that case, and we already consume carrier market data ourselves
(Trailblazer supply ships, Trade Route results). No special-casing needed.

## Design

**Trigger**: `main_window.py`'s existing `"Market"` journal-event handler
(the one that already calls `_load_current_market()` to read `Market.json`
for our own UI) additionally calls
`self.eddn_publisher.maybe_publish_commodity(market_json_data)`, passing
the already-parsed dict — one file read, two consumers, no new I/O.

**New code**, both in `edc/core/eddn_publisher.py`:

- `build_commodity_message(data: dict) -> Optional[dict]` — pure function,
  mirrors the existing `build_message()`. Validates required top-level
  fields are present, walks `Items[]` applying the elisions/renames/skip
  rules above, returns `None` if the result would have zero commodities
  or is missing a required field (malformed/partial `Market.json`).
- `EddnPublisher.maybe_publish_commodity(data)` — mirrors
  `maybe_publish()`: same beta-build skip, same
  `eddn_contribute_enabled` gate (checked by the caller, same as today),
  builds the `commodity/3` payload (`$schemaRef` =
  `https://eddn.edcd.io/schemas/commodity/3`), pushes onto the *same*
  existing `self._queue` / worker thread / retry logic — no new queue, no
  new thread.

**Gating**: reuses `eddn_contribute_enabled` — no new setting, no new UI.

**Fleet Carriers**: included, not special-cased.

**No dedup logic**: `Market` only fires when the commodities screen is
actually opened, so natural frequency is low enough that occasional
duplicate submissions for the same station visit aren't worth the added
complexity.

## Testing

Synthetic, no live posting required to verify correctness (the POST/retry
path is already proven by the existing journal publisher):

- Feed a real-shaped `Market.json` dict (based on the one confirmed
  above) through `build_commodity_message()`; assert every required
  elision/rename/skip rule is applied correctly and the result validates
  against `commodity-v3.0.json`'s required-field list.
- A Limpets/NonMarketable item in the input must not appear in the
  output.
- A malformed/partial input (missing `Items`, missing `MarketID`, etc.)
  must return `None`, not raise.
