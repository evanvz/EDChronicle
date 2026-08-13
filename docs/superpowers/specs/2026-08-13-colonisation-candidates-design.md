# Colonisation Candidates — Design

## Context

EDChronicle already tracks *active* colonization construction well
(`colonisation_depots` table, Squadron tab card, built 2026-08-11 — manual
add, save-on-visit, distance-sorted list, progress %, resource breakdown,
"find nearest supplier"). It has zero coverage of the *pre-construction*
phase: figuring out which nearby systems are actually eligible to claim
before committing a 25M-credit non-refundable fee and a trip.

Surfaced while reviewing competitor tools (VoidCompass's "Colonisation
Recon", Raven Colonial's system planner, both referenced via BGS-Tally's
wiki) — a real gap already flagged once before (2026-08-06/2026-08-11,
noted in memory) and now explicitly picked by the user as the one worth
building.

## Research

Real game mechanics, verified via primary sources this session (not
guessed):

- A system is colonizable only if genuinely unpopulated, **and** within
  15 ly of an existing populated system — claimed via a System
  Colonisation Contact, found at any starport. (A second mechanic exists —
  10 ly chained expansion from your own already-built colony's own new
  contact, once its primary starport is built — explicitly out of scope
  for this pass per the approved design: only the 15 ly current-location
  rule is implemented.)
- Claiming costs a non-refundable 25 million credit fee.

EDSM's public `sphere-systems` API directly answers the eligibility
question and is already reachable from this app (the User-Agent-blocking
issue that broke all EDSM calls was root-caused and fixed earlier this
session). Confirmed live, not assumed:

```
GET https://www.edsm.net/api-v1/sphere-systems?systemName=Sol&radius=15&showInformation=1
```

Populated systems return a full `"information"` object
(`population`, `allegiance`, `government`, `faction`, etc.). Genuinely
unpopulated systems return an **empty** `"information": {}` — confirmed
directly: querying radius=100 around Sol returned `"GMB 3689"` at 98.53 ly
with `"information":{}`, while every populated neighbor carried full data.
This is EDSM's own signal for "no known population," which is exactly the
"is this system unpopulated" question this feature needs answered.

This session already got burned once by an unthrottled EDSM call pattern
(a real 720/hour rate-limit outage, already fixed elsewhere in the
codebase) — this design's throttling section exists specifically to avoid
repeating that mistake.

## Design

### 1. `edc/core/colonisation_eligibility.py` (new)

Two functions, both hitting EDSM's `sphere-systems` endpoint (same
plain-`requests`-plus-identifying-User-Agent pattern already established
elsewhere in this codebase for EDSM calls, e.g.
`edc/core/edsm_faction_lookup.py`):

```python
def find_nearby_colonisation_candidates(system_name: str, radius_ly: float = 15.0) -> list[dict]:
    """Unpopulated systems within radius_ly of system_name, closest first,
    capped at 20. Each result: {"name": str, "distance_ly": float}."""

def check_system_eligibility(system_name: str) -> dict:
    """For a manually-named candidate system: is it itself unpopulated,
    and is there a populated system within 15 ly of it (the claim
    requirement). Returns {"eligible": bool, "reason": str,
    "nearest_populated_ly": Optional[float]}."""
```

Both parse the same `"information": {}` vs populated-`"information"`
signal already confirmed above. Network/parse errors return an empty
list / an `{"eligible": None, "reason": "lookup failed"}`-shaped result
rather than raising — matching this codebase's established EDSM-call
error-handling convention.

### 2. Throttling

The passive candidates list is only re-queried when the player's **current
system changes** (`FSDJump`/`Location` events) — not on every HUD refresh
tick, which fires far more often. Result is cached in memory (current
system name + its candidate list), reused for every refresh until the next
system change. No persistence needed — this is inherently "what's near me
right now" data, matching how other current-location-relative lookups in
this codebase (e.g. engineer-distance tables) already work without a
database table.

### 3. UI — Squadron tab (`edc/ui/panels/squadron_panel.py`)

New card, "COLONISATION CANDIDATES — WITHIN 15 LY", placed next to the
existing "COLONISATION CONSTRUCTION — TRACKED SITES" card:

- A simple two-column list (System, Dist (ly)) of the current cached
  candidates, closest first. Empty state: "No unpopulated systems found
  within 15 ly of \<current system\>." while genuinely empty; a distinct
  note if the lookup itself failed (EDSM unreachable) vs. a real empty
  result.
- Below it, a manual-check row: a text input (system name) + a "Check"
  button, calling `check_system_eligibility()` on click (not throttled —
  a one-off user action, not a per-refresh poll) and showing the
  eligible/not-eligible result with its reason inline.
- A fixed caveat line under the card: "Advisory only — based on EDSM's
  crowdsourced population data, which can lag real-time changes. Confirms
  what's in range, not that you're currently at a valid Colonisation
  Contact."

### 4. Wiring (`edc/ui/main_window.py`)

The existing `FSDJump`/`Location` dispatch (already the trigger for
several other per-jump refreshes this session, e.g. faction snapshots)
gains a call to refresh the cached candidates list, threaded through to
`squadron_panel.refresh(...)` the same way other panel state already
flows from `main_window.py`.

## Testing

`find_nearby_colonisation_candidates()`/`check_system_eligibility()`'s
JSON-parsing logic (populated-vs-empty `"information"` detection, distance
sort, cap) is synthetic-testable against a mocked/fixture EDSM response
shape — no live network call needed for the unit tests themselves, mirroring
this codebase's existing convention for other EDSM-parsing functions.
Live verification (the actual HTTP call reaching EDSM and returning sane
data) confirmed the same way other EDSM integrations in this session were
verified — a direct live query during development, not a live call inside
the automated test suite. UI wiring (the new card, the manual-check flow,
the throttle-on-jump behavior) verified visually/live in-app, matching this
project's established convention for panel-level changes.
