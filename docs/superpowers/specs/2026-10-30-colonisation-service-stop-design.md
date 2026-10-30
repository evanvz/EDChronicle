# Colonisation "Service Stop" Score and System Design Window

Date: 2026-10-30. Owner: Evan. Builds on `2026-10-29-colonisation-system-finder-design.md` (shipped).

## Why

Evan wants to colonise (with his squad) systems that are good for **general players** and that **grow on their own**
(the system's NPC side: population, development, tech level). He is not after personal profit. The finder's current
score (`10 × port types + economy types`) cannot tell a good home system from a scattered one: it ignores distance,
how bodies group around a parent, slot counts and the "top two economies" rule.

## What a good system is (Evan's words)

"As many services as possible. Not so blank market. Place to hand in discovery. Fix their ship. Hand in exo
discovery, perhaps outfitting." Call this a **service stop**.

| Want | Game service | How a colony gets it (sources below) |
|---|---|---|
| Hand in discoveries | Universal Cartographics | default on T3; on a T2 orbital / T1 surface port via a Comms, Satellite or Relay installation in the same orbit (strong link) |
| Hand in exobiology | Vista Genomics | as above, or Medical installation / Scientific Hub (system unlock) |
| Fix the ship | repair, refuel, rearm | every station, even a construction site |
| Outfitting | outfitting | default on T2/T3 orbitals; T1 surface ports via High Tech Hub (system unlock) or Industrial Hub (strong link); stock scales with tech and development level |
| Shipyard | shipyard | default on T2/T3 orbitals; T1 surface ports via Industrial Hub (system unlock), High Tech Hub (strong link) or Military Installation |
| Market not blank | well-stocked commodities | at most two economies per port (top two are protected from cannibalisation); more population and wealth raise supply |

## Goals

1. **Service-stop score** per claimable system in the finder, with a short reason text, sortable, alongside the old score.
2. **System design window** (popup from a selected finder row): the user picks the body showing the primary-port flag
   in the game's Architect View; the window either gives a phased build plan mapped onto that system's real bodies,
   or marks the system a **poor pick** with the reason.

## Non-goals

- Exact economy percentages (Raven Colonial's job; Dubior notes it has its own errors). Rules, not maths.
- Profit layouts (Wing Mining Missions, mining, trade) — Evan declined profit as the goal.
- Sending data to Raven Colonial or any third party (standing rule: logic-only reuse).
- Guessing the primary-port slot. Only the game shows it; the user tells the window.

## Anti-goals (failure even if it "works")

- A plan that recommends a T3 primary for a solo hauler without saying it needs a group (≈250 kt in 4 weeks).
- A plan that mixes 3+ economies into the main port (blank market).
- Presenting community-reported rules as official. Every rule carries its source; unverified ones say so.

## Data (EDDataHub)

The Spansh galaxy dump already carries per body: `radius` (km), `gravity` (g), `surfaceTemperature` (K),
`atmosphereType`, `terraformingState`, `volcanismType`, `rotationalPeriodTidallyLocked`, `parents`, `rings`,
`signals`, `isLandable`, `distanceToArrival` (checked in the server's dump 2026-10-30). The hub keeps only
`name, sub_type, landable, distance_ls, port_types, economies` today.

- New migration adds the body fields the rules need (parent body id, rings flag, atmosphere present, terraformable,
  geo/bio signal flags, tidally locked, radius, gravity, temperature) to `colonisation_bodies`, plus the service-stop
  score and reason on `colonisation_systems`. A full re-import (≈53 min) fills them.
- **Ground slot estimate** (Dubior, Advanced ED Colonisation Guide, 2026-08-11, "Slot Count", community research):
  0 if temperature ≥ 700 K or gravity ≥ 2.7 g; else radius <1500 km → 1, <3750 → 2, <6000 → 3, ≥6000 → 4;
  +2 atmosphere, +1 terraformable, +1 high metal content, +1 geologicals; max 7. Orbital slots are not in the dump:
  assume 0–3 per body (guide), shown as "unknown" rather than invented.

## Service-stop score (hub, computed at import)

A system is scored around its best **cluster**: a parent body plus its moons (from `parents`). Inputs, all from the dump:

- cluster distance from arrival (shorter is better; Evan: "first planet from system entry shorter distance is better");
- landable moons and their estimated ground slots (room for a surface port, hubs, settlements);
- bodies giving High Tech and Industrial (tech level → outfitting/shipyard stock; development level → stock);
- Earth-like / water / ammonia worlds (population and High Tech / Agriculture; weighted up);
- rings in the cluster (Extraction / wealth, asteroid base option);
- penalty when the cluster's natural economies exceed two families that cannibalise each other.

Weights are the builder's call, written in one table in code with a comment per weight, and must keep the three
systems examined on 2026-10-30 in this order: Tucanae Sector PY-R b4-1 (cluster 3 at 898 ls, 6 landable moons) above
ICZ KX-T b3-3 (cluster A 4 at 1,717 ls) above CD-55 35 (cluster 1 at 5,477 ls).

The finder shows a new "Service stop" column (score) with the reason as tooltip, e.g.
"Gas giant 3 at 898 ls: 6 landable moons, ~14 ground slots, rings; Industrial + High Tech". Default sort becomes
this column. The old score stays as a column.

## System design window (EDChronicle)

Opened from a selected finder row (button "Design…"). Shows the system's bodies grouped by cluster and a
**"Primary slot body"** picker (default: unset, with the hint "Find the flag in the system map's Architect View").

Once a body is picked:

- **Poor pick** (red banner, no plan) when the primary body is not in a cluster with at least one landable moon /
  surface slots within reach, or is a lone star or far-out body (exact thresholds: builder's call, listed in one place).
- Otherwise a **phased plan** mapped to real body names:
  1. Primary: Coriolis (solo) or T3 (group) — states the tonnage and the 4-week limit; T3 gives Cartographics,
     Vista, shipyard and outfitting at once.
  2. Same orbit: Comms or Relay installation → Cartographics + Vista on a Coriolis (+ security).
  3. Surface port on the primary body if it has ground slots (raises the station's population/market).
  4. Mining Installation → Industrial Hub on a moon (shipyard at T1 surface ports, development level).
  5. High Tech Hub on a moon (outfitting, tech level).
  6. Optional growth: Space Farm / Agriculture settlement on bio/terraformable bodies, Medical installation (Vista).
  - Each step lists the services it unlocks and its prerequisite.
  - Per port: expected top-two economies, with a warning when a step would add a third cannibalising economy.
- Footer: sources with dates; a line that the controlling faction comes from the claim station.

## Sources (read 2026-10-30)

- CMDR Dubior, *Advanced Elite Dangerous Colonization Guide* (Google Doc, ref. 2026-08-11): slot counts, top-two
  economies, service rules, stats, faction placement, black markets.
- CMDR PhoenixBlue0, *Colonization 101* (Google Doc): primary-port rules, build orders, support-project unlocks.
- DaftMav, *Service Unlocks flowchart* (image Evan supplied).
- Body economies: existing `colonisation_rules.json` (gaborauth/ed-colonisation-planner, Update 3 patch notes).

## Decisions from the builder check (Claude's calls unless marked)

- **Where logic lives:** the hub owns clusters, slot estimates and the service-stop score (one place, tested there).
  `/api/colonisation-system` is extended to return per body `cluster` (root body id), `ground_slots` (int or null)
  and the raw flags; `/api/colonisation-search` keeps every existing field and adds `service_score` and
  `service_reason`. EDChronicle owns only the plan template and poor-pick verdict, built from those fields — no
  slot or cluster logic in the app. A rule change in the score needs a hub deploy (Evan runs deploys).
- **Rollout:** migration `020_colonisation_service_stop.sql`. Until a row is re-imported, `service_score` is NULL:
  the column shows blank and sorts below scored rows; the old score stays visible. **Evan's call:** after the deploy,
  force one full Spansh run (≈53 min) so every row gets the new fields, instead of waiting up to 30 days.
- **Fixtures:** the three named systems' records are read from the hub DB/dump read-only (claude_ro, or
  `zcat` of the server's dump) and trimmed to fixture JSON in the hub tests.
- **Clusters:** walk `parents` skipping `Null`/barycentre entries; a body's cluster root is its nearest Planet
  ancestor, else the body itself if it is a Planet. A Planet orbiting a star directly roots its own cluster (may have
  zero moons). Stars and belts are not cluster roots; a star's belt counts as "rings" for the star only.
- **Missing inputs:** high metal content = `subType` "High metal content world". If radius, gravity or temperature is
  missing, `ground_slots` is null (shown "?"), contributes 0 to the score, and the reason says "slots unknown".
- **Reason vs window:** the finder reason describes the best-scoring cluster; the window plans around the
  user-picked primary body's cluster. They may differ; the window says so ("best cluster is X").
- **Plan scope:** fixed phase order, steps already satisfied are skipped (e.g. T3 primary skips step 2; a primary on
  a body with no ground slots skips step 3). Primary type: a Solo/Group toggle in the window (default Solo →
  Coriolis; Group → T3 Orbis/Ocellus by ring presence).
- **Cannibalisation penalty:** Dubior's "Mixed Economy Setups" table: Agriculture/Extraction/Refinery/Tourism mix
  well; Industrial and High Tech "don't work well with any other economies"; Refinery+Industrial is the worst pair.
  Penalty applies when a cluster's natural economies include Industrial or High Tech together with any other
  family, or Refinery with Industrial. The window shows the same rule as a per-port warning.
- **Market before outfitting (Evan, 2026-10-30: "favour a full market"):** the main port stays at its natural top
  two economies. High Tech builds (High Tech Hub, Relay) go on a *different* cluster when the system has one; if it
  has none, the plan leaves them out and says outfitting stock stays at the default. Step 5 changes accordingly, and
  the score rewards a second cluster that can take High Tech.

## Left to the builder

Score weights and poor-pick thresholds (one table each, commented); window layout (follow the app's tab/table
style); how the plan text is templated; test fixtures built from the three named systems.
