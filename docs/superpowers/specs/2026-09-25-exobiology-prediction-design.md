# Exobiology Species Prediction — Design

## Context

Following a review of EDEXO-Compare (https://github.com/bahuckel/EDEXO-Compare),
the commander asked whether EDChronicle could predict which exobiology
species can exist on a planet from an FSS scan alone, before landing or
running a DSS/probe pass. EDEXO-Compare does this with a full
probabilistic model calibrated against ~39,000 real Spansh sightings
(claims 97.8% accuracy in its top confidence band) — we don't have that
calibration corpus locally, and building/maintaining one is a
significantly bigger lift than this feature needs to start.

Checked `edc/ui/panels/exobiology_panel.py`: EDChronicle has no
prediction feature today, only a display of species already confirmed
via `CodexEntry`/genus-species-variant detection after an actual scan.
This is a real gap, not a duplicate of existing functionality.

Placement: the Exploration tab, attached to each scanned body, the
moment its physical data is available (FSS-level detail is enough for
most species' conditions) — matching the commander's own stated purpose
of knowing before landing, not after.

Scope: a simple qualify/disqualify list ("these species COULD be here"),
not a confidence score — each species has known min/max ranges for
gravity, temperature, pressure, and a required atmosphere/planet-type/
volcanism/host-star set; a body either falls inside every one of a
species' rules or it doesn't. No statistical weighting.

## Research

**Data EDChronicle already has**: `persistence/repository.py::save_body`
already persists `planet_class`, `volcanism`, `surface_gravity`,
`surface_temperature`, `surface_pressure`, `atmosphere_type`,
`atmosphere`, `atmosphere_composition` per body (from `Scan`/
`SAASignalsFound` journal handling in `main_window.py`, already wired).
The matcher needs no new per-body data collection — it reads the `bodies`
table Repository already fills as every scan happens live.

**Data EDChronicle does NOT have**: the host star's spectral class
(needed for star-type-gated species, e.g. Electricae Radialem only near
white dwarfs) and galactic-region membership (needed for a handful of
region-restricted species, e.g. some Aleoida variants exclude the
Orion-Cygnus/Sagittarius-Carina cores). Star type is confirmed available
from the system's own `Scan` event for its primary star (`StarType`
field) — same event pipeline already ingested, just not currently kept
on `state`/`bodies` in a form this matcher can read; needs one new
column. Region membership has no existing lookup anywhere in this
codebase and would need either a bundled region-boundary dataset or a
network call — **out of scope for v1**: region-restricted species are a
small minority of the codex and this is a `qualify` gate players can
still verify by eye once landed, not a hard requirement for the feature
to be useful. Flagged as a known ceiling, not silently dropped.

**Structured per-species habitat data**: does not exist anywhere in
EDChronicle today. `settings/exo_values.json` (118 species) has
`base_value`/`genus`/`ccr_m`/free-text `traits` for payout calculation
only — `traits` entries like `"CO2"` or `"B or O-Class Stars"` are
human-readable hints, not structured min/max ranges a matcher can
evaluate. Confirmed via `EDMC-BioScan`'s open-source ruleset
(https://github.com/Silarn/EDMC-BioScan, GPL-2.0) exactly what a real
per-species rule looks like (`src/bio_scan/bio_data/rulesets/*.py`):

```python
'$Codex_Ent_Aleoids_01_Name;': {
    'name': 'Aleoida Arcus',
    'rulesets': [{
        'atmosphere': ['CarbonDioxide'],
        'min_gravity': 0.04, 'max_gravity': 0.276,
        'min_temperature': 175.0, 'max_temperature': 180.0,
        'min_pressure': 0.0161,
        'body_type': ['Rocky body', 'High metal content body'],
        'volcanism': 'None',
    }],
}
```

**Licensing note**: BioScan's own code/data files are GPL-2.0;
EDChronicle is PolyForm-Noncommercial-licensed, and folding a GPL data
file in wholesale would be a real license-compatibility problem, not
just a style choice. The underlying facts (a given species' known
gravity/temperature/pressure range) are not copyrightable — only
BioScan's specific expression of them (their Python data structure) is —
so the plan is to independently re-derive the same per-species numeric
thresholds from Canonn's own published community data (canonn.fyi/
biosheet, and Canonn's own wiki/codex pages, e.g.
https://canonn.science/codex/stratum/), not copy BioScan's files. This
is slower to build (manual/semi-automated transcription from a
non-machine-readable-by-default source) but avoids the license question
entirely. BioScan's ruleset stays a **reference for which fields matter
and how they're structured**, not a data source.

## Architecture

**New table** `exo_habitat_rules` (bundled, shipped with the app, not
fetched over the network — same shape decision as `exo_values.json`,
which is also a bundled static file, not a live-fetched cache):

```sql
CREATE TABLE IF NOT EXISTS exo_habitat_rules (
    species          TEXT NOT NULL,
    genus            TEXT NOT NULL,
    atmosphere       TEXT,       -- JSON list, e.g. ["CarbonDioxide"], NULL = any
    min_gravity      REAL,
    max_gravity      REAL,
    min_temperature  REAL,
    max_temperature  REAL,
    min_pressure     REAL,
    max_pressure     REAL,
    body_type        TEXT,       -- JSON list, e.g. ["Rocky body", "High metal content body"]
    volcanism        TEXT,       -- JSON list, or "None", or "Any"; NULL = any
    star_type        TEXT,       -- JSON list of accepted primary-star spectral classes; NULL = any
    PRIMARY KEY (species)
);
```

Loaded once at startup the same way `exo_values.json` already is
(`edc/core/exo_values.py`, confirmed existing loader) — a new sibling
`edc/core/exo_habitat.py` module loading `settings/exo_habitat.json`
(same bundled-JSON pattern, not a DB table populated by a migration,
since this is static reference data the app ships with, not something
accumulated from play).

**Matcher** (`edc/core/exo_predictor.py`, new, pure functions, no I/O):
`predict_species(body: dict, star_type: str | None) -> list[dict]` —
`body` is the same shape `Repository.get_bodies_for_system`/the live
`state.bodies` entries already use. For each rule, every non-null
min/max bound and every non-null set-membership field (atmosphere,
body_type, volcanism, star_type) must pass; a rule field left `None`
means "no constraint from this rule." Returns the matching species list,
each with its known `base_value` joined in from the existing
`exo_values` loader (players care what a predicted find is worth) sorted
by value descending.

**Star type on bodies**: add `star_type` to `bodies` table (one more
`ALTER TABLE`, same idempotent pattern already used throughout this
session) — populated from the system's own primary-star `Scan` event
(`event.get("StarType")`), same trigger point `save_body` already fires
from. Only meaningful for the body actually orbiting/near that star
(single-star systems only for v1 — multi-star systems where a candidate
body's actual local star isn't the system's primary are a known,
documented gap, not silently wrong: the predictor treats "unknown star
type" as "don't gate on star_type", which is a safe under-restrictive
default, not a false negative).

**Exploration panel integration**: `exploration_panel.py`'s existing
per-body card (already renders planet_class/gravity/atmosphere/etc for
each scanned body) gets a new "Possible exobiology" sub-section, calling
`predict_species()` with that body's row + the system's star_type,
showing genus/species names (color-coded by genus, reusing the same
palette convention as the Session Activity Report's per-faction colors)
with their known value. Hidden entirely when the list is empty (no
"None found" clutter) or when the body doesn't support life-bearing
signals at all (existing `landable`/atmosphere-presence checks the panel
already does elsewhere reused, not duplicated).

## Testing

`exo_predictor.py`'s `predict_species()`: pure-function unit tests, no
DB/Qt — feed synthetic body dicts against a small in-test ruleset,
confirm each bound (gravity/temp/pressure/atmosphere/body_type/
volcanism/star_type) correctly includes/excludes, confirm a rule field
left `None` doesn't over-constrain, confirm sort-by-value-descending.
`exo_habitat.py`'s loader: confirm it parses the bundled JSON into the
same shape the matcher expects, mirroring `exo_values.py`'s own existing
test coverage if any exists (check before writing new patterns).
`save_body`'s new `star_type` column: extend the existing body-save test
file(s) rather than writing a new one. Exploration panel rendering:
manual/live confirmation only, per this project's own testing convention
(exploration features need live journal confirmation, not just green
tests) — FSS-scan a body with a well-known species (e.g. a CO2 Rocky
body around 175-180K should predict Aleoida Arcus) and confirm the
predicted list matches what's actually found on landing.
