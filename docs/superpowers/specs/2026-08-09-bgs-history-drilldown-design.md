# BGS Influence History Drill-Down — Design

## Context

`faction_snapshots` (schema, save/query methods, and trend/expansion/retreat/
conflict-risk predictions) already exists and is already live — it is not
new work. What's missing is a way to see a **tracked-but-not-currently-visited**
system's day-by-day influence history from the Player Faction tab, without
adding to the already-full 10-column bucket dialog table (`System, Influence,
Controlling, Active, Pending, Reputation, Action, Forecast, Distance,
Remove`), where `Action` and `Forecast` are both `Stretch`-resized and
already visibly truncated.

Scope, per explicit decision: history is captured only for systems already
tracked on the Player Faction tab (not passively for every system visited),
and retained for a rolling 30 days per system+faction (bounded DB growth;
one row/day already exists at this cadence since the real BGS tick is
once/day).

## Design

**Bucket dialog table** (`edc/ui/panels/player_faction_panel.py`,
`_FactionBucketDialog`): drop the `Forecast` column (10 → 9 columns).
Change `System` from `Stretch` to a fixed, still-resizable width like the
other columns, so `Action` becomes the sole `Stretch` column and gets the
freed width — this also fixes today's Action-text truncation.

**New drill-down**: clicking a row's `Influence` cell opens a small
non-modal `_FactionHistoryDialog`, kept alive via a dict on the bucket
dialog the same way `_ColonisationDetailDialog` instances are kept alive
on the Squadron panel. It shows:
- the Forecast text/color that used to live in the table column, computed
  the same way it already is today (`_format_forecast()` +
  `Repository.get_faction_predictions()`)
- a plain table of the real daily snapshots for that one system+faction
  (Date, Influence %, Active state), newest first

**Backend**: extend `Repository.get_faction_history(system_address,
faction_name=None)` with an optional faction filter (keeps the Intel tab's
existing all-factions call working unchanged). Add a prune step inside
`save_faction_snapshot()` — `DELETE FROM faction_snapshots WHERE
system_address=? AND faction_name=? AND snapshot_date < date('now',
'-30 days')` — run after each upsert, since no retention limit exists
today.

No schema change. No new table. No new persistence pipeline.

## Out of scope

- No charting/sparkline — a plain date-sorted table, consistent with how
  every other detail dialog in this app (Colonisation depots, bucket
  dialogs themselves) already presents tabular history.
- No passive history capture for untracked systems.
- No change to the Intel tab's existing current-system history display.
