# Expansion Forecast — design

**Date:** 2026-10-08
**Status:** approved in conversation, awaiting written-spec review
**Scope:** BGS only, the squadron faction (today Elite United Worlds). PowerPlay acquisition candidates are a separate, later spec.

## Purpose

The squad wants to see where its faction's next BGS expansion is heading, before and after it happens:

- **Before:** which of its systems is about to expand, and a ranked shortlist of where it is likely to land.
- **After:** the system it actually expanded into, as soon as anyone reports it, shown until the next expansion.
- **Alert:** a short notice whenever the faction appears in a system it hasn't been seen in before.

Success: on 2026-10-07 the app would have shown "Expanded into Tucanae Sector YF-W b2-2 (9.1%), likely from Ekono" on its own, rather than someone finding it by querying the database. The forecast gives a useful shortlist and says plainly when it cannot be sure.

## What prompted it

On 2026-10-07 Ekono dropped 11.1% (expansion tax) and EUW appeared in Tucanae Sector YF-W b2-2 at 9.1% (EDDN, 16:59 UTC). The app had the data but nothing pointed at it.

A backtest against EDSM showed the prediction limit: Arimavante (10.9 ly from Ekono, 6 factions, no EUW, visited by the player 2026-09-26) should have been preferred over YF-W (28.2 ly) by the rules below. The likely reason is that EUW was there before and retreated (that demotes a system), before the app began tracking. The forecast must show that uncertainty, not hide it.

## Constraints

- No full minor-faction datastore: only a small cache of the shortlisted candidates.
- "Has the faction been there before" uses only the app's own history. `save_faction_snapshot` prunes a system/faction's rows older than 30 days each time a new snapshot for that same system and faction is saved (journal rows flagged `is_squadron_faction = 1` are kept). So while the faction is present its rows roll over, but once it has left a system no new snapshots arrive and its last rows stay. History therefore goes back to when tracking began (2026-07-30 in this database); anything earlier is unknown.
- Network lookups and the cube query (about 4 s on the real DB) run off the UI thread. SQLite connections are per thread, and QThreads stay referenced for their lifetime.
- The faction is never hard-coded: it is the squadron faction from `Repository.get_squadron_faction_name()`.

## Game rules used (community-researched, not Frontier documentation)

Source: the squad bot's `docs/expansion-logic.md` (Padrino-d3), which cross-checks its Java predecessor against the Complete BGS Guide 2025, pp. 63–67; and the SINC Complete BGS Guide 2024 (expansion above 75%, about 15% expansion tax).

- **Source system:** the faction's system that has been above 75% influence for at least a day; if several qualify, the highest influence.
- **Search area:** a cube of ±20 ly on each axis around the source (up to about 34.6 ly straight-line), not a sphere.
- **Candidates:** populated systems in the cube where the faction is not present now.
- **Priority:**
  1. fewer than 7 factions and the faction has never been there → nearest first;
  2. fewer than 7 factions and the faction has been there before (it retreated) → nearest first;
  3. exactly 7 factions → an invasion war (lowest-influence non-native faction).
- Systems with 8 factions are never targets.
- If nothing qualifies, the game searches ±30 ly next; if still nothing, the expansion fails. (Ekono's expansions ending 2026-08-09 and 09-11 took no tax, which may be failed expansions — unconfirmed.)

## Design

### 1. Data

**Watched systems.** The squadron faction's systems at **≥ 70%** influence, from the latest snapshot per system (`get_faction_history` / `faction_snapshots`). For each: influence, days at or above 75% (consecutive, from the snapshot history), and the Expansion state (pending / active / recovering, from the state lists).

**Likely source.** Among watched systems, the one with the highest influence that has been ≥ 75% for at least a day. If none has, the highest-influence watched system, marked "not yet eligible".

**Candidates.** For the likely source, systems from `system_coords` inside the ±20 ly cube, joined to `net.system_bgs_status` for population; keep population > 0, drop systems where the faction is present now (latest snapshots), order by straight-line distance. Systems with unknown population are left out (78 of 168 in Ekono's cube); the tab says how many were skipped for that reason.

**Lookups.** For the nearest **10** candidates, fetch the faction list from EDSM with the existing `edsm_faction_lookup.fetch_system_factions()` (rate-limited, retries) on a background worker. Store per candidate: system name and address, distance, faction count (factions with influence > 0), whether the squadron faction is listed, fetched-at time.

**Cache table** (new, in the main DB):

```sql
CREATE TABLE IF NOT EXISTS expansion_candidates (
    source_address  INTEGER NOT NULL,
    system_address  INTEGER,
    system_name     TEXT    NOT NULL,
    distance_ly     REAL,
    faction_count   INTEGER,
    faction_present INTEGER,
    fetched_at      TEXT    NOT NULL,
    PRIMARY KEY (source_address, system_name)
);
```

Refreshed at most **once a day** per source, automatically when the tab opens and the cache is older than that, or by a "Refresh lookups" button. Old rows for a source are replaced on refresh.

**Faction history.** "Been there before" = yes if `faction_snapshots` ever had the squadron faction in that system; otherwise "unknown (before tracking)". There is no "no" answer.

### 2. Ranking

Pure function, no I/O, in a new module `edc/core/expansion_forecast.py`:

- Tier 1: faction count < 7 and no known history → nearest first.
- Tier 2: faction count < 7 and known history → nearest first.
- Tier 3: faction count == 7 → nearest first (invasion war).
- Excluded: faction count ≥ 8; candidates not looked up yet are listed after the ranked ones as "not checked".
- If no candidate is in tiers 1–3, the tab shows: "No eligible system within ±20 ly — the game would search ±30 ly next, or the expansion fails." The ±30 ly search itself is not built.

Every ranked row carries the caveat on screen: *A closer system can be skipped if the faction left it before tracking began.*

### 3. Screen — Faction Expansion Tracker → "Forecast" tab

The Faction Expansion Tracker (`faction_expansion_dialog.py`) becomes a two-tab window: the existing content as tab 1 ("Target system"), and a new tab 2, **Forecast**, built in its own widget module `edc/ui/panels/expansion_forecast_panel.py`.

Forecast tab, top to bottom:

1. **Next to expand** — table of watched systems: system, influence, days ≥ 75%, state; the likely source highlighted.
2. **Likely targets** — for the likely source: rank, tier, system, distance, faction count, "faction here before", data age; "Refresh lookups" button; status line (looked up N of M, skipped K with unknown population); the caveat line. One click on a row copies the system name, as elsewhere.
3. **Last result** — "Expanded into X on DATE (INF%)", from the new-system detection below, shown until the next expansion ending is detected. Includes "likely from SOURCE" when an expansion ended in a faction system within ±1 day.

### 4. New-system alert

Detection, pure function in `expansion_forecast.py`: a system whose earliest squadron-faction snapshot is within the last 3 days, with influence above 0 and at most 20% = "new system". The 20% cap keeps a long-held system that the app only just fetched for the first time (e.g. an import) from showing as new; a faction arriving by expansion starts small (9.1% in YF-W). It is a heuristic, not a game rule. Paired with an expansion ending (the existing `faction_expansion_dialog.expansion_endings()` logic, moved to `expansion_forecast.py` and imported back so there is one copy) within ±1 day in another faction system → "likely expansion from X".

Shown for 3 days as:
- a line on the Overview, e.g. `🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%) — likely expansion from Ekono`;
- a line at the top of the Session BGS Activity Report (under the PowerPlay row);
- the Forecast tab's "Last result".

All rich text built from these names is HTML-escaped (names come from EDDN).

### 5. Error handling

- EDSM lookup fails or is blocked: keep the previous cache rows, mark them stale, show "lookup failed — showing data from DATE".
- No squadron faction known: the tab says so and shows nothing else.
- No watched system: "No faction system at 70% or more."
- The worker never touches widgets; it emits results to the UI thread, following the existing worker pattern (`_ExpansionLookupWorker` in the same dialog).

## Testing

- Unit tests for `expansion_forecast.py` with real data from 2026-10-07/08:
  - cube membership (YF-W at dx 19.7, dy 8.8, dz 18.2 is inside; a system at 21 ly on one axis is not);
  - ranking: Arimavante (6 factions, no known history) ranks tier 1 above YF-W only by distance; a 7-faction system goes to tier 3; 8 factions excluded; unlooked-up rows last;
  - new-system detection: YF-W first seen 2026-10-07 pairs with Ekono's expansion ending 2026-10-07 → "likely from Ekono";
  - expansion endings still found after the move (existing tests keep passing).
- Repository test for the cache table: replace-on-refresh, once-a-day staleness.
- One render test of the Forecast tab with a fake repository.
- Done means seeing it in the running app (project rule): the Forecast tab for Elite United Worlds, the alert line, and a lookup refresh.

## Out of scope

- PowerPlay acquisition candidates (separate spec).
- Refreshing candidate faction counts from EDDN.
- The ±30 ly extended search.
- Predicting invasion-war targets beyond "tier 3".
