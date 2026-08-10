# Material Trader Advisor — Design

## Context

Many players (including the user) find Elite Dangerous's Material Trader
up/down-trade mechanic hard to reason about manually. The ask: given
materials the player has plenty of (easy to farm, currently unneeded),
suggest a real, correct trade toward whatever's short for an
Engineering wishlist item — a new card on the Engineering tab, separate
from the existing missing-materials list.

## Research (already done, grounding this design)

The exact trade math was **not** reliably available from wiki summaries
(two independent searches produced internally-inconsistent ratios).
Sourced the real, authoritative rules directly from
[EDEngineer](https://github.com/msarilar/EDEngineer) (MIT licensed), a
mature, widely-used community tool built for exactly this purpose —
its `MaterialTrader.cs`/`MaterialTrade.cs` implement the live trade
logic, and `Resources/Data/entryData.json` has the complete material
dataset:

- Every Raw/Manufactured/Encoded material has a **Rarity** (grade:
  VeryCommon → Common → Standard → Rare → VeryRare) and a **Group**
  (the tradeable "family" — e.g. `Category6`, `Category7`,
  `ShieldData`).
- **Same-group trade** (same family, any grade): 3:1 down a grade, 6:1
  up a grade, multiplicative per grade jumped (e.g. up 2 grades = 36:1).
- **Cross-group trade** (different family, same Raw/Manufactured/Encoded
  type): only works **down-or-equal** grade — trading a lower-grade
  material *up* into a different family is not possible at all. Flat
  6:1 at equal grade; a 2×-penalty variant of the down-grade formula
  when both crossing groups and dropping grade.
- `Kind: "OdysseyIngredient"` entries (suit/weapon materials) are a
  different game system entirely (different vendors, not the ship
  Material Trader) — out of scope for this card.

Confirmed existing app pieces this reuses, not rebuilds:
- `state.materials_raw` / `materials_manufactured` / `materials_encoded`
  (`edc/core/state.py`) — live-tracked owned quantities, keyed by
  internal material name.
- `EngineeringPanel.missing_materials_for_wishlist()`
  (`edc/ui/panels/engineering_panel.py`) — already returns
  `{material_symbol: shortfall_amount}` across both the ship and
  Odyssey wishlists combined.

## Design

**Data**: new `edc/core/material_trading.py` with a static table derived
from EDEngineer's `entryData.json`, `{internal_name: (grade_rank, group)}`
for Raw/Manufactured/Encoded materials only (excludes Commodity and
OdysseyIngredient entries — not part of this trade system). File header
credits EDEngineer (MIT license) as the data source.

**Algorithm**: `find_material_trades(shortfalls, owned, excess_threshold=30)`
in the same file — a pure function (no Qt/DB), ported from EDEngineer's
own `AllTrades`/`FindPossibleTrades`:
- Excess pool = owned materials with count > `excess_threshold`, **excluding**
  anything that's itself in `shortfalls` (don't suggest trading away a
  material you're also short on).
- For each shortfall, evaluate same-group candidates (all grades) and
  cross-group candidates (down-or-equal grade only) from the excess
  pool, compute the exact units needed per EDEngineer's formulas, and
  pick the cheapest (same-group always beats cross-group when both are
  available, since cross-group's ratio is worse at every grade delta).
- Tracks running consumption across shortfalls (EDEngineer's `deduced`
  dict) so one excess material isn't suggested as the source for more
  total shortfall than it actually has spare.
- A shortfall with no valid covering trade is simply omitted from
  results, not shown as an error.

**UI**: new card on the Engineering tab (`edc/ui/panels/engineering_panel.py`
or a small new panel it composes), one row per missing wishlist material
with a trade suggestion: *"Need: `<material>` (short N) ← Trade `<M>`
units of `<source material>` (X spare)"*. Refreshes automatically
whenever the Engineering tab refreshes — the computation is pure
in-memory Python over small dicts, cheap enough that there's no reason
to gate it behind a manual button the way the heavier DB-backed
searches (Market, Trade Routes) are.

## Out of scope

- Odyssey suit/weapon materials (different vendor system).
- Real per-grade storage caps — "excess" is a simple fixed count
  threshold (>30), not a percentage of each material's actual max
  capacity, since no verified cap data exists in the app yet and this
  keeps the feature shippable without another research round.
- Multiple ranked trade options per shortfall — one best suggestion per
  row, per explicit decision.
- Any UI for manually browsing "what could my excess become" outside
  the context of an actual wishlist shortfall.
