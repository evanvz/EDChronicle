# Engineers Reference Tab — Design

## Context

EDChronicle already tracks per-engineer unlock progress from the live
journal (`EngineerProgress` event, parsed in
`edc/engine/handlers/engineers.py` into `state.engineer_progress[name] =
{engineer_id, rank, progress, rank_progress}`, persisted across restarts
by `edc/core/engineer_progress_store.py`) and already has every engineer's
location/coordinates (`engineering_blueprints.json`'s `engineer_locations`,
38 entries, full coverage of every real in-game engineer). What's missing
is a browsable reference showing *why* each engineer matters — their
discovery method, meeting requirements, and unlock requirements — cross-
referenced against the status EDChronicle already knows.

User supplied a real, complete list of all in-game engineers with their
requirement text (`Engineers.txt`, this session) as the data source. The
list's `î ï¸` sequences are mojibake — a warning-icon emoji mangled by a
copy-paste encoding mismatch — not meaningful content, cleaned during data
entry.

Explicitly scoped down in a prior exchange with the user: this tab shows
each engineer's *overall* status (Not Encountered / Invited-in-progress /
Unlocked at rank N) — not a per-requirement-bullet checklist. Most
individual "meeting requirements" reference CMDR combat/trade/exploration/
federation/empire ranks, which EDChronicle does not currently track at all
(confirmed: `state.py` has zero rank fields). Others are cumulative
counters (e.g. "traded in over 50 markets") with no single journal-exposed
signal to check off, or one-time material provisions only knowable in
hindsight once the engineer is already unlocked. None of that is being
retrofitted here — this tab is a reference + overall-status view, matching
what's honestly derivable today.

## Design

### 1. `settings/engineer_requirements.json` (new)

One entry per engineer, keyed by name (matching the exact name strings
already used as keys in `engineering_blueprints.json`'s
`engineer_locations`, so the two files join cleanly):

```json
{
  "last_updated": "2026-08-13",
  "source": "User-supplied compilation of official/community engineer unlock data",
  "engineers": {
    "Felicity Farseer": {
      "discover": "Public data sources.",
      "meet": "Gain exploration rank Scout or higher.",
      "unlock": "Provide 1 unit of Meta Alloys."
    }
  }
}
```

`discover`/`meet`/`unlock` are plain display strings, cleaned of the
source file's mojibake artifacts. Some real engineers have no separate
"meet" step (a few late-game/Colonia engineers go straight from discovery
to unlock) — that key is simply omitted for those entries rather than
stored empty, and the UI skips rendering a blank line for a missing key.

### 2. New "Engineers" sub-tab (`edc/ui/panels/engineering_panel.py`)

A third tab alongside the existing Ships / Suits & Weapons tabs in
`EngineeringPanel`'s `QTabWidget`. A new `_EngineersTab(QWidget)` class,
following this file's established per-tab-class pattern.

Layout: a scrollable list of per-engineer `QFrame` cards (not a table —
each entry is multi-line text, poorly suited to table rows), matching the
card visual style already used elsewhere in this codebase (Intel panel,
Odyssey candidates). Each card shows: engineer name, system + distance
from the player's current position (using the same `system_x/y/z`
reference-position pattern already used by this file's other distance
displays), discover/meet/unlock text, and a status line.

Cards are grouped into three sections — **Unlocked**, **In Progress**,
**Not Encountered** — each sorted alphabetically by engineer name within
the section. This makes the tab read as "what am I still missing" at a
glance rather than a flat A-Z list a player has to scan entirely.

### 3. Status derivation

Reuses the exact status logic already established in this file's existing
"Available From" engineer-distance tables (`_refresh_engineer_table()` in
both existing tabs), simplified since there's no specific target grade to
compare against here:

- No entry in `state.engineer_progress` for this engineer → **Not
  Encountered**.
- Entry exists, `rank` is an int `>= 1` → **Unlocked — Rank {rank}**.
- Entry exists, `rank` is `0`/`None` but `progress` is a non-empty string
  (e.g. `"Invited"`) → **{progress} — not yet unlocked** (In Progress
  section).
- Entry exists but neither of the above → **Not Encountered** (defensive
  fallback for an unexpected/empty progress record).

### 4. Data flow

No new state fields, no new journal parsing, no new persistence — this
tab is a pure read of two already-existing sources
(`engineer_requirements.json` loaded once at startup the same way
`engineering_blueprints.json` already is; `state.engineer_progress` and
`state.system_x/y/z` already flow into `EngineeringPanel.refresh(state)`)
joined by engineer name at render time.

## Testing

Pure UI/reference-display feature with no new business logic to unit
test — matches this file's established convention (every other
Engineering panel change this session was verified live, not synthetically
tested). Verified live: the tab renders all 38 engineers correctly
grouped, an engineer actually unlocked in-game shows in the Unlocked
section with the correct rank, and distances match the existing
"Available From" tables' own distance numbers for the same engineer (a
cheap cross-check that the coordinate join is correct, reusing data
already proven correct elsewhere in this file).
