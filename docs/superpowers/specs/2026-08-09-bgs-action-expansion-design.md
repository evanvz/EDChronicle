# BGS Action Line Expansion — Design

## Context

`derive_bgs_action()` (`edc/ui/panels/player_faction_panel.py:99`) already
gives a state-specific headline for a tracked system (War, Election,
Outbreak, Boom, pending Expansion/Retreat, etc.), shown in the bucket
dialog's Action column. Two real gaps, confirmed by direct review:

1. It only ever shows **one** line, which reads as "this is the only thing
   I can do here." In reality, general Influence-boosting activities
   (profitable trade, bounty vouchers redeemed, missions completed — all at
   a station the tracked faction controls) apply in **every** system
   regardless of its current state; a crisis-specific remedy (e.g.
   Outbreak's medicine delivery) resolves that crisis mechanic, it doesn't
   replace the baseline BGS activities.
2. Several states the bucket-tile grid already recognizes (Incursion,
   Infested, InfrastructureFailure, NaturalDisaster, Revolution, ColdWar,
   TradeWar, TerroristAttack, PublicHoliday, TechnologicalLeap,
   HistoricEvent, Colonisation) have no case in `derive_bgs_action()` at
   all, so a system in one of these silently falls through to "Stable
   control — no action needed," which is wrong — something is actually
   happening there.

## Design

**Baseline hint, always appended.** Wrap the existing state-matching logic
in a small private core function; the public `derive_bgs_action()` appends
one short, constant reminder to whatever headline the core returns:
`"Also always helps: trade, missions & bounty vouchers at their stations."`
This means every Action line becomes "(specific thing, if any) + (the
general thing that's always true)" instead of implying the specific thing
is the only lever.

**New state cases**, added honestly rather than guessed:
- `Colonisation` gets a real, confident, specific tie-in: contributing
  construction materials helps (the app's own Squadron-tab colonisation
  tracking already built this session).
- The remaining recognized-but-unhandled states (Incursion, Infested,
  InfrastructureFailure, NaturalDisaster, Revolution, ColdWar, TradeWar,
  TerroristAttack) get a short, accurate label naming what's actually
  happening, without inventing a specific delivery-commodity fix I can't
  verify — most of these (Thargoid-related, or general economic/political
  tension) don't have a well-documented single-commodity remedy the way
  Outbreak/Famine/Drought do.
- `PublicHoliday`, `TechnologicalLeap`, `HistoricEvent` are positive/flavor
  states, not crises — labeled as such rather than implying something needs
  fixing.

No existing line's wording changes (Outbreak/Famine/Drought/etc. stay as-is
— out of scope, not reported wrong); only the new baseline suffix and the
new state cases are added.

## Out of scope

- Not verifying/rewriting the pre-existing per-state remedy text (Blight,
  etc.) — not something reported as inaccurate, and changing it isn't part
  of this request.
- No personal contribution tracking (explicitly declined — user chose
  "recommend what to do," not "log what I did").
