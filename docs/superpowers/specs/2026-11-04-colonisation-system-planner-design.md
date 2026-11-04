# Colonisation system planner — design

Date: 2026-11-04. Status: draft, awaiting Evan's review.
Repos: EDChronicle (Design window, planner) and EDDataHub (slot store, scoring fix).

## Why

The Design window plans every system with one fixed template. That template doesn't know how many slots each body has, which kind of system the squad wants, or how construction points flow. The hub's score also penalises economy "clashes" under a rule Frontier changed in August 2025.

Two well-built systems show what good builds look like:
- ICZ DR-M b7-1: 23 facilities, every slot filled, one economy theme per body, points spent on two Tier 3 ports.
- Col 359 Sector LC-T d4-17: 78 planned facilities in the same pattern.

Evan wants the build itself to work this way:
1. Choose what the system is for.
2. Enter the real slot counts.
3. Get a plan fitted to the system.

## Goals

1. **System type selector** in the Design window: Refinery, Service stop, Full build.
2. **Slot counts per body** (orbital and surface), from the best available source, editable, and shared with the squad through the hub.
3. **A plan for each type**, fitted to the known slots. It accounts for construction points (CP), including the port cost ramp, plus facility requirements and the service-unlock rules. It warns when the plan doesn't fit.
4. **Economy rule corrected** in both the app and the hub: two economies in a market no longer cannibalise each other.

## Non-goals

- Optimal solving with integer programming, like gaborauth's ed-colonisation-planner. The first version uses rules.
- Pushing plans or slot counts to Raven Colonial. Raven Colonial is read-only for us here.
- Commodity tonnage per facility, or haul planning.
- Choosing the primary-port body. The game decides it; the user picks the body the game flags.
- Changing the finder's "Score" (10 × port types + economies).

## Anti-goals

- A plan that silently uses more slots than the body has, or slots we don't know about. Unknown means "not counted", with a warning.
- Presenting an estimate as fact. Every slot count shows where it came from.
- Losing the current template plan. It remains the fallback when a system has no slot data.

## Facts this rests on (checked 2026-11-04)

- **Construction points.** Sources: ED wiki "System Colonisation" facility tables, read through its API; Mega Guide v1.3.2 by CMDR Mechan.
  - Tier 1 facilities cost nothing and give 1 T2 (yellow) point.
  - Tier 2 facilities cost 1 T2 point and give 1 T3 (green) point. Large settlements give 2.
  - Coriolis and Asteroid Base cost 3 T2 and give 1 T3.
  - Tier 3 ports (Orbis, Ocellus, Dodec, T3 Planetary Port) cost 6 T3.
- **Port cost ramp** (Mega Guide). The primary is free and doesn't count. Each further T2/T3 port costs more:
  - T2 ports: 3, 3, 5, 7, 9 … (3 + (n−2)·2);
  - T3 ports: 6, 6, 12, 18, 24 … ((n−1)·6).
  - Other facilities don't ramp.
- **Requirements**, from the wiki's "Requires" column:
  - Industrial Hub needs a Mining outpost.
  - Military Installation needs a military settlement.
  - Research station needs a scientific settlement.
  - Tourist installation needs a tourism settlement.
  - Exploration hub needs a Communication station.
  - Outpost hub needs a Space farm.
  - Extraction hub needs an extraction settlement.
  - Civilian hub needs an agricultural settlement.
  - Security Station needs a Relay station.
- **Service unlocks** (Update 3.3, via the Mega Guide):
  - A Tier 3 port has every service from the start.
  - A Tier 2 port has its market, shipyard and outfitting from the start. Universal Cartographics and Vista Genomics need a strong link to a Satellite, Comms or Relay installation, a Scientific installation, or an Exploration Hub.
  - Tier 1 ports need hub links plus tech level 35 for shipyard and outfitting.
- **Economy (Frontier, 2025-08-21/22).** Quoted by the wiki and forum threads; the official page refused automated reads:
  - The top two economies in a market are not cannibalised.
  - Only a third or later economy can be eaten.
- **Strong links:** a facility's economy feeds the ports on or orbiting the same body. Weak links reach the whole system.
- **Slots:**
  - Surface slots follow Dubior's formula. It matched all 25 player-entered surface counts in DR-M b7-1 and LC-T d4-17.
  - Orbital slots have no known formula.
  - Raven Colonial's slot counts are typed in by the architect, not read from the game: SrvSurvey's client "intentionally" leaves slots out, and records carry edit histories.
- **Building:** up to five facilities can be under construction at once. Nothing can be undone.

## Slot sources (in order of trust)

1. **Entered on the hub (squad).**
   - New table: `colonisation_slots (system_id64, body_id, orbital, surface, cmdr, updated_at)`, primary key `(system_id64, body_id)`.
   - Written through `PUT /api/colonisation-slots`, granted to the web role in `deploy/web-role.sql`, the same pattern as marks.
   - Returned in `/api/colonisation-system` as `orbital_slots` / `surface_slots` plus `slots_source` on each body.
2. **Raven Colonial, player-entered.** Read through the existing GET client (`/api/v2/system/{name}`, field `slots`: `{body num: [orbital, surface]}`, −1 = none). Matched to bodies by name.
3. **Estimate.** The hub's `ground_slots` covers surface only. Orbital is unknown.

The Design window shows each body's orbital and surface counts with a source tag (entered / Raven / est. / ?). They're editable; Save writes source 1 for the squad.

## The selector and the plans

Common to every type:
- The plan starts from the primary port on the chosen body (free).
- It places facilities only into known free slots.
- Steps are ordered by dependency and available CP.
- It shows the running T2/T3 balance and the ramp.
- It respects the five-at-once limit as a note.
- It lists slots left over and any unknown counts.

**Refinery**
- **Aim:** a metals market at the primary.
- **On the primary's body:** a Refinery Hub, then extraction or industrial-free support. Keep the primary body's market to at most two economies.
- **Elsewhere:** Tier 1 facilities with no economy (Satellite, Comms) for points and the Universal Cartographics / Vista Genomics links.
- **Warnings:** no surface slot on the primary's body, which means no Refinery Hub.

**Service stop**
- **Aim:** every service at the primary as quickly as possible.
- **Tier 3 primary:** done after the primary. Then add security if a security stat goes negative.
- **Tier 2 primary:** add a strong link at the same body for Universal Cartographics and Vista Genomics: a Comms installation (not Relay, which adds High Tech; Evan's earlier rule), else a Satellite.
- **Size:** the smallest facility list that does this.

**Full build**
- **Aim:** fill every known slot, like DR-M b7-1 and LC-T d4-17.
- **Themes:**
  - Give each body or cluster one economy theme, from the body's own economies (`body_economies`) and its slot room.
  - Keep each market to at most two economies.
  - Put a security cluster where the Tier 3 ports push security below zero.
- **Order:**
  1. Tier 1 facilities first, for T2 points.
  2. Large settlements, for 2 T3 points each.
  3. Tier 3 ports before Tier 2 ports, because of the ramp.
  4. Remaining slots with Tier 1 or Tier 2 facilities that fit the theme.
- **Ends with:** the final CP balance, and how many Tier 3 ports the slots can pay for.

## Economy rule fix

- **App:** `colonisation_design._clash` warns only when a market would hold three or more economies, or when a facility would add a third economy to a body's market.
- **Hub:** `service_stop.cannibalises` applies the same three-or-more rule. A full colonisation import (about 5 h) re-scores afterwards.
- Both change together, as the twin comment in the code already says.

## Projected outcome

Every plan ends with a summary row (Evan, 2026-11-04):
- **System stats**, summed over the primary and every planned facility: population, max population, security, wealth, tech level, standard of living, development. These are the same effect values Raven Colonial sums for its home-page filters.
- **Total haul** in tonnes, and tonnes per step.
- **Score in Raven Colonial's style:** the sum of a fixed score per facility (Tier 3 port 15, Coriolis/Asteroid 8, hub 5, …). It's for comparison with systems on ravencolonial.com only, never for ranking candidates. An unbuilt system scores 0.
- **Warnings:**
  - security below 0 after any step (Tier 3 ports cost security);
  - for Tier 1 ports that need it, tech level below 35. Whether the game's tech level is this same sum is unverified, so the warning says so.

Reference points, checked against Raven Colonial 2026-11-04:
- ICZ DR-M b7-1 (all 23 built): score 101, 762,740 t; pop 36, max pop 31, security 14, wealth 44, tech 24, standard of living 40, development 44.
- Col 359 Sector LC-T d4-17, whole plan of 78: score 309, 1,860,937 t.

## Facility data

- New `settings/colonisation_facilities.json`. Per facility: name, Raven Colonial/SrvSurvey build-type keys, tier, location, economy, requires, CP cost/reward, haul tonnes, Raven-style score, and effects (pop, mpop, sec, wealth, tech, sol, dev).
- **Main source:** Raven Colonial's facility table in its site bundle (`ravencolonial.com/static/js/main.*.js`, read 2026-11-04). It's the most complete and includes tonnes and score.
- **Cross-check:** the ED wiki facility tables, plus SrvSurvey's `colonization-costs2.json` for build-type names. Values differ in places, for example the Coriolis: Raven Colonial gives tech 2 / wealth 3 / dev 3, the wiki tech 1 / wealth 2 / dev 2. The file lists each difference in a `wiki_differs` field, so it can be checked in game.
- The file carries a `source` field and the date read, like the other reference files.

## Left to the builder

- How themes are scored when a body offers several economies (a simple rule, documented in code comments).
- The UI layout of the slot grid inside the Design window.
- Body-name matching to Raven Colonial (exact name; skip any body that doesn't match).
- Tests per plan type, built on the DR-M b7-1 and LC-T d4-17 shapes as fixtures:
  - every slot used;
  - CP balance never negative;
  - requirements met before use;
  - the primary is free and doesn't ramp.

## Live confirmation

- Enter the slots for one real candidate system, pick each type, and compare the plan with the Architect View.
- After the hub re-score, IN-S b4-0 loses the clash penalty: Extraction + Industrial is two economies.
