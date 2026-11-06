# Exobiology Prediction — Design

Replaces `2026-09-25-exobiology-prediction-design.md`, which was declined. Its objection to external data no longer
applies (Evan reopened the feature on 2026-11-06, knowing the rules come from outside), and its licence argument is out
of date: the repo is GPL-3.0 now.

## Why

When a system or planet has biological signals and nobody has visited before, the app shows only a count until the
planet is DSS mapped. Evan flies exobiology for credits, so what he wants at that moment is which planet is worth flying
to. Value is what decides it (his answer).

The feature fills the unknown with clearly labelled possible genera and species, plus an "up to" value.

## Goals

- A body with biological signals and known physical facts shows possible genera and an "up to" value before DSS.
- After DSS, the possibilities narrow to the genera DSS found.
- After sampling, real data replaces everything.
- Bodies rank by value, so the best one to fly to is at the top.
- Overview shows one short line for a high value planet in the current system, nothing more.

## Non-goals

- **No voice alert or toast** for a possible planet (Evan's decision). Alerts stay for confirmed finds.
- **No probabilities or confidence scores.** A species could be here or it can't.
- **No colour variant prediction.**
- **No network fetch.** The rules ship with the app.
- **No full list on Overview.** Evan: "we already have too much going on the overview".

## Anti-goals: failure even if it technically works

- A guess that looks like a confirmed find.
- A guess saved into `BioGenuses`, `state.bio_genuses`, the codex data or any other store of real finds. Guesses are
  worked out when shown and never persisted.
- "Up to" being presented as what the planet will pay.

## Evidence

A throwaway script tested the rules against all of Evan's journals on 2026-11-06. Applied: atmosphere, body class,
gravity, temperature, pressure, volcanism, atmosphere composition, distance from arrival, orbital period, other body
types in the system, star rules. Not applied, counted as a pass: region, nebula, Guardian ruins, tuber zones, named
system.

| Measure | Result |
|---|---|
| Sampled species the rules allow | 907 of 910 (all 3 misses on HIP 87621 2 b a) |
| DSS genera predicted before DSS | 1489 of 1491 |
| Predicted genera that were really there | 51.3% |
| Species candidates per body before DSS | median 4, max 22 (2024 bodies) |
| Genera narrowed to one species after DSS | 1108 of 1489 |
| Real total inside low..high on fully sampled bodies | 194 of 194 |
| Median on those bodies | real 20.67M, "up to" 20.67M, low 1.6M |

The 194 bodies are biased, because Evan chose to sample them. They show "up to" doesn't undersell a planet, not that
most planets reach it.

Share of bio bodies and systems at each "up to" threshold: 2M 71%/80%, 10M 40%/51%, 20M 28%/39%, 30M 10%/16%, 50M 2%/3%.

## Behaviour

### Display states for a body with biological signals

| Knowledge | Shown |
|---|---|
| Signal count only, no physical facts (no `Scan`) | The count, as today. No guess. |
| `Scan` known, no DSS | The count as fact, plus possible genera and "up to" |
| DSS done (`BioGenuses`) | Real genera, each with its possible species if more than one; "up to" limited to those genera |
| Sighting known (`CodexEntry` or EDDN sighting of that species on this body) | That genus shows the sighted species and its value, with no guesses for it; other genera follow the rows above |
| Sampled | Real species and value replace the possibilities for that genus |

A body counts as sampled for a genus from its first `ScanOrganic`, because that names the species. The player's own DSS
and sampling win over a sighting from another commander if they differ. Sightings stay input to the predictor: the panel
passes them in, and the predictor still does no DB access.

Possible items must look different from real ones: the word "possible" plus a dimmer style. Confirmed items keep their
current style.

### "Up to" value

- **Before DSS:** for each possible genus take the highest base value among its species that fit the body. Add the top
  N of those, where N is the body's biological signal count. Each genus counts once, because Odyssey allows one species
  per genus per body.
- **After DSS:** the same, over only the genera DSS found. Today's per-genus figure
  (`edc/ui/panels/exobiology_panel.py`, `genus_max`) is the genus's best anywhere, so limiting it to species that fit
  this body makes it more honest.
- **Sighted or partly sampled genus:** counts at its real value, and takes up one of the N.
- **Finished genus (`ScanOrganic` `Analyse`, 3 of 3 samples):** no longer counts, because "up to" means what's still left
  to earn on this body. Its real value still shows beside it. A fully sampled body has no "up to".
- **Base value only.** The first-logged ×5 bonus is not included.
- **Genus rule for all eras.** Each genus counts once, Horizons-era ones included. It may undersell a Horizons body with
  two species of one genus; the 194 of 194 result above used this same rule.

### Where it shows

- **Exobiology tab and Exploration body cards:** both show the possible list and "up to". These are the screens Evan
  uses when hunting exobiology for credits.
- **Ranking:** bodies rank by "up to", highest first, on the Exobiology tab. Its sort today is
  `(_status_rank, -value)`, line 649; possible bodies have to rank by value against each other. Exploration's own sort
  order is left alone unless the builder finds a need.
- **Overview:** one clickable line that opens the Exobiology tab, for example
  `🧬 High value exo planet: Synuefe 9 a, up to 41M`. Only the best planet in the current system. Shown when its "up to"
  (what's still left to earn) meets the threshold, so it clears by itself as the planet gets sampled. Silent.

### Threshold

New setting `exo_overview_alert_m`, default 30 (Evan agreed 30M; about 1 system in 6 in his journals). It has its own
slider next to the existing one in Settings. `exo_high_value_m` (default 2) keeps its current meaning and is not reused.

## Data

New bundled file `settings/exo_habitat.json`, cut down from EliteNexus `data/exobiology/species.json`
(https://github.com/uruskan/EliteNexus, GPL-3.0-or-later, commit to be recorded in the file's meta when copied). Keep
per species: genus, species, codex name, `rulesets`, `sources`. Drop what isn't used, including `era` and `certainty`.

- Use `rulesets` only, not the wider `conditions` envelope.
- Keep all species that have rules, Horizons-era included, with no filter on certainty. That is the set the evidence
  measured.
- Thargoid entries have no rules and are left out.
- Values come from our `settings/exo_values.json` (fact-checked 2026-10-14). A test must flag any species in the new file
  without a value there.
- Their per-species values are not used, except to check ours (a test or one-off comparison); differences get reported to
  Evan, not silently resolved.

**Credit:** add EliteNexus and its underlying sources (EDMC-BioScan, SrvSurvey, Canonn) to `THIRD_PARTY_NOTICES.md`, and
keep the `sources` fields in the data, as EliteNexus's own notes ask.

## Rule semantics

These are from `docs/research/exploration.md` §2.5 in EliteNexus and were used in the journal test:

- A species fits if any of its rulesets passes. A ruleset passes if all its constraints pass.
- `g = SurfaceGravity / 9.797759`; `atm = SurfacePressure / 101231.65625`. `max_pressure_atm` is exclusive. A missing
  value skips that test.
- Volcanism: `"none"` needs empty, `"required"`/`"any"` needs non-empty, `{"contains_any": [...]}` is a lower-case
  substring test.
- Star rules: `star_anywhere_in_system` looks at any star in the system; `parent_or_primary_star` looks at the body's
  `Parents` stars and the star at distance 0. Entries are a class or `[class, luminosity]`. Class matching: `A` also
  matches `A_BlueWhiteSuperGiant`, `B` `B_BlueWhiteSuperGiant`, `F` `F_WhiteSuperGiant`, `G` `G_WhiteSuperGiant`, `K`
  `K_OrangeGiant`, `M` `M_RedGiant` and `M_RedSuperGiant`; `D`, `C`, `W` match by prefix; others are exact. Luminosity
  `IV` also matches `IVa`, `IVb`, `IVab`, `IVz`.
- `system_has_body_type`: some planet in the system has one of the listed `PlanetClass` values.
- **Partly known systems: never rule a species out on what hasn't been scanned yet.**
  - `star_anywhere_in_system` and `system_has_body_type` apply only when `state.fss_complete` is true (set by
    `FSSAllBodiesFound`, already reset on jump). Until then they pass, and if it never fires they keep passing. This avoids
    `resolved_body_ids` against `system_body_count`, which `main_window.py` comments call unreliable after DB backfill.
  - `parent_or_primary_star` applies only when every star in the body's `Parents` has been scanned.
  - The list can shrink and "up to" can fall as FSS finishes. It never grows from this, so the ranking may reorder.
  - The evidence above ran on finished journals, so early lists will be somewhat wider than it shows. Recall isn't hurt.
- **v1 passes these without testing:** region, nebula, Guardian ruins, tuber zones, named system. That is what the evidence
  above measured. It lists too much rather than too little, so it stays honest. Region can come later.

## What the app needs that it lacks today

- **Stars aren't kept.** No code reads `StarType`, `Luminosity` or `Parents`; star `Scan`s return early at
  `edc/core/event_engine.py:1435`. Keep the current system's stars in memory on `state`, and add `Parents` to the body
  record. Reset them on system change, the same way other per-system state is reset.
- **No schema change.** Star data lives in memory only. After a restart in a system, or for bodies loaded from the DB,
  star rules are skipped, so the list is wider, not wrong.
- **Atmosphere spelling trap.** `event_engine.py:1487` prefers `AtmosphereType_Localised`, and DB rows hold what the
  importer saved. Rules use raw names such as `CarbonDioxide`. The matcher must normalise before comparing and a test must
  cover both spellings. The same check applies to `Volcanism` at line 1443.
- **Bodies without facts.** Records can exist with an empty `PlanetClass` (signals arrived first, or EDDN/Spansh data).
  No `PlanetClass` or no gravity means no prediction.

## Structure

- `edc/core/exo_predictor.py`: pure functions, no I/O or Qt, in the style of the existing `edc/core/exo_values.py`
  loader. Loads the file, matches a body, works out "up to".
- Panels call it at display time, on the UI thread only if it stays cheap (about 120 species times a few rulesets per
  body); it does no DB access.
- `exploration_panel.py` builds a card `signature` (line 577) to decide when to rebuild. New displayed data has to be part
  of it or cards won't update.

## Testing

- Unit tests on the matcher: each rule type includes and excludes; both atmosphere spellings; missing values skip; star
  rules skipped when stars are unknown or the system is unfinished; "up to" with N signals, after DSS, with a sighting,
  partly sampled, and fully sampled.
- A test that guesses never reach `BioGenuses` or `state.bio_genuses`.
- Live confirmation, as the project rules require for exobiology: FSS a system with biological signals, compare the list
  and "up to" before DSS with what DSS and sampling reveal, and confirm Evan sees it work. The issue stays open until he
  confirms.

## Left to the builder

- Exact wording, colours and layout, inside "possible" being clearly different and dimmer.
- How the Overview line attaches: `overview_actions` already handles an `exobiology` link
  (`overview_panel.py:619`, built in `main_window.py` near line 6701); `next_up` doesn't take links today.
- How possible bodies mix with the status groups on the Exobiology tab, as long as value decides between possible bodies.
