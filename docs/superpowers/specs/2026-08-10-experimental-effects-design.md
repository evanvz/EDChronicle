# Experimental Effects — Design

## Context

The Engineering tab's ship wishlist tracked a blueprint's primary grade
material cost, but had no concept of Experimental Effects — the optional
secondary modifier applicable at an Engineer alongside a blueprint, each
with its own flat (non-grade-scaling) material cost. Flagged as a gap
while reviewing the tab; approved to build immediately.

## Research

`EDCD/coriolis-data`'s `modifications/specials.json` has all 91 known
Experimental Effects with flat material costs (component names as
display strings). Joined to internal lowercase symbols via
`EDCD/FDevIDs`'s `material.csv` (name → symbol), the same join already
used to build `engineering_blueprints.json`. One coriolis-data typo
("Encyptors" missing an 'r') needed a manual override. 4 of the 91
effects have no known cost data in coriolis-data at all (a pre-existing
gap in that source, same as blueprint/engineer coverage elsewhere in
this app).

No compatibility data exists anywhere (which effects are valid for
which module type) — confirmed via direct check of coriolis-data's
schema. Building a hand-maintained compatibility map was explicitly
rejected: any gap in a hand-made mapping risks wrongly hiding a valid
choice, worse than showing all 91 unfiltered.

Also found and fixed along the way: `edc/core/material_trading.py`'s
material key table (built from `EDEngineer`'s `entryData.json`
`FormattedName` field) was wrong for 22 Encoded/Data materials whose
display name has a rarity-flavor adjective the real internal symbol
omits — confirmed via `FDevIDs`/`material.csv` and the user's own live
journal data. Fixed by re-deriving every key from `FDevIDs` where
possible, falling back to `entryData.json`'s field only for the handful
of newer materials `FDevIDs` doesn't have yet (validated against the
same live journal).

## Design

**Data**: `settings/experimental_effects.json` — `{edname: {name,
components: {symbol: qty}}}`, same provenance/non-commercial-fan-use
framing as the existing blueprint data.

**Code**: `edc/core/experimental_effects.py`, `ExperimentalEffectsTable`
— `effect_names()`, `display_name(edname)`, `requirements(edname)`,
`has_known_cost(edname)`.

**Wishlist**: `engineering_wishlist.py` entries gain an `experimental`
field (edname or `None`). Old saved entries load with `None`.

**UI**: `_ShipEngineeringTab`'s add-form gets a second dropdown
("— None —" default) next to Grade, with a warning note when the
selected effect has no known cost. A new `_combined_requirements(entry)`
helper sums the blueprint's cumulative requirements with the chosen
effect's requirements; it replaces the direct blueprint-requirements
calls in `_missing_count`, `missing_materials_for_wishlist`, and
`_refresh_detail_table`, so the shortfall count, the Materials Required
table, and the Material Trader Suggestions card all account for the
effect automatically. The wishlist table row shows `(+ <effect name>)`
when one's picked.

## Out of scope

- ~~Effect-to-module compatibility filtering (no data source exists).~~
  Revisited same day for weapons specifically — see addendum below.
- Merc Coin / Operations update tracking — deferred; no journal event
  found in the official manual or the user's own journal history
  (they haven't run Operations content yet), and no community data
  source exists yet either. Revisit once real data is available.

## Addendum: per-weapon-type effect filtering (2026-08-10)

The broad "weapon" category effect list (44 entries) turned out to be
real-but-inaccurate for a specific weapon — the real game restricts many
effects to specific hardpoint types (e.g. Auto Loader only makes sense on
ammo weapons, not lasers). Re-checked coriolis-data and found the actual
compatibility data does exist, just not in `specials.json`:
`modifications/modules.json` has a `specials` array per module-group code
(e.g. `"mc"` for Multi Cannon), and `modules/hardpoints/*.json` filenames
map cleanly to those codes via each file's `grp` field. Pulled all 30
hardpoint types this way — 11 have real effects (9-12 each), the other 19
(Missile Racks, Guardian weapons, AX weapons, Mining Laser, etc.)
genuinely have zero in-game, matching known mechanics.

Added `weapon_type_effects` to `experimental_effects.json` and a
`weapon_type` field to wishlist entries. A new "Weapon Type:" dropdown
appears only for weapon blueprints (default "— Any weapon —", preserving
the original broad list for old entries); picking a specific type narrows
the Experimental Effect dropdown to that hardpoint's real list, including
correctly showing zero options where that's the truth.
