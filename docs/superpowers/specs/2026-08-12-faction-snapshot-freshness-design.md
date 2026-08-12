# Faction Snapshot Freshness Comparison — Design

## Context

`faction_snapshots` is written by three independent pipelines — the
player's own journal visits, the daily/tick-triggered EDSM refresh (plus
manual add and CSV import, all EDSM-backed), and the passive EDDN
listener — all through the same upsert, keyed by `(system_address,
faction_name, snapshot_date)` where `snapshot_date` is calendar-day
granularity only. Whichever write happens to land last in wall-clock
time silently wins, with no actual comparison of which write's
*underlying data* is more recent. A delayed EDSM refresh completing
after a fresher EDDN sighting earlier the same day can silently
overwrite better data with worse data.

Surfaced investigating a real discrepancy: EDChronicle showed a
system's War state as "pending" while Inara — and EDSM itself, queried
live — already showed it "active." Root cause was EDSM's own
crowdsourced data lagging the real game state at the moment we queried
it, not a bug in our parsing. But the investigation exposed that even
if a fresher answer had arrived through a different pipeline, nothing
in this table would have known to prefer it.

## Research

All three pipelines already carry (or can trivially carry) a real
per-event timestamp for the *data itself*, confirmed by reading each
write path directly — none of it is currently persisted:

- **EDSM**: a live query today showed each per-faction response
  includes `"lastUpdate": <unix epoch int>` — currently parsed and
  discarded in `edsm_faction_lookup.py::_fetch_once()`.
- **EDDN**: `eddn_market.py::write_buffers()`'s `factions` buffer
  already carries a `timestamp` (from the journal/1 message) — currently
  truncated to just its date (`timestamp[:10]`) for `snapshot_date`, the
  rest thrown away.
- **Personal journal visits**: `main_window.py::_save_faction_snapshots()`
  is called from the main event-dispatch method, which has the
  triggering event's own `timestamp` in scope, just not currently
  threaded through.
- **CSV import fallback** (when EDSM doesn't list the faction for a
  CSV-imported system at all): `player_faction_panel.py`'s CSV worker
  already reads `row.get("updated_date")` as a `snapshot_date` fallback
  today — the same field is the right freshness source for this case
  too, since there's no EDSM `lastUpdate` to use.

**Format mismatch risk, must be normalized before storage.** EDSM's
`lastUpdate` is a Unix epoch (needs conversion to a string), and journal
timestamps use a `...SSZ` suffix. If two otherwise-identical UTC
instants are stored with different suffix conventions (`Z` vs `+00:00`),
naive lexical string comparison in SQL would rank them incorrectly
relative to each other, since `Z` (ASCII 90) and `+` (ASCII 43) differ
as characters regardless of the actual instant they represent. This
project already has established normalization logic for exactly this
mismatch (`trade_routes.py::_parse_ts()`, built earlier this session for
the same reason) — reused here rather than re-solved.

## Design

**Schema** (`persistence/database.py`, new migration):

```sql
ALTER TABLE faction_snapshots ADD COLUMN data_timestamp TEXT;
ALTER TABLE faction_snapshots ADD COLUMN source TEXT;
```

`data_timestamp`: the real-world moment the underlying data was true,
normalized to one consistent format (`YYYY-MM-DDTHH:MM:SSZ`) so lexical
string comparison sorts correctly. `source`: one of `"journal"`,
`"edsm"`, `"eddn"`, `"csv"`.

**`persistence/repository.py`** — `save_faction_snapshot()` gains two
new required parameters:

```python
def save_faction_snapshot(
    self,
    system_address: int,
    faction: dict,
    snapshot_date: str,
    is_controlling: bool,
    data_timestamp: str,
    source: str,
):
```

Passed explicitly by every caller, matching how `is_controlling`/
`snapshot_date` already work as explicit parameters rather than dict
keys smuggled through `faction`.

The upsert's `DO UPDATE` gains a `WHERE` guard (SQLite supports a
conditional `DO UPDATE ... WHERE`, no read-then-compare round trip
needed):

```sql
ON CONFLICT(system_address, faction_name, snapshot_date) DO UPDATE SET
    influence = excluded.influence,
    ... (existing columns, unchanged) ...
    data_timestamp = excluded.data_timestamp,
    source = excluded.source
WHERE faction_snapshots.data_timestamp IS NULL
   OR excluded.data_timestamp >= faction_snapshots.data_timestamp
```

Pre-existing rows have `NULL` in the new column — the `IS NULL` branch
means the very next real write from any pipeline naturally backfills
them. No migration/backfill script needed.

**`edc/core/edsm_faction_lookup.py`** — `_fetch_once()`'s per-faction
dict building currently discards `f.get("lastUpdate")`. Add it to each
built faction dict as `"LastUpdate"` (Unix epoch int, converted to the
normalized string format at the point each of the three EDSM-backed
call sites reads it out — keeping the conversion logic in one shared
helper rather than duplicated three times).

**Call site changes** (all in `player_faction_panel.py` /
`main_window.py` / `eddn_market.py`):

- `main_window.py::_save_faction_snapshots()` gains a `timestamp: str`
  parameter, passed the triggering event's own `evt.get("timestamp")`
  from its one call site; `source="journal"`.
- `player_faction_panel.py`'s bulk refresh worker, single-system add,
  and CSV import's EDSM-matched branch: read `faction.get("LastUpdate")`,
  normalize, pass as `data_timestamp`; `source="edsm"`.
- `player_faction_panel.py`'s CSV import fallback branch (EDSM doesn't
  list the faction): use the already-referenced `row.get("updated_date")`
  as `data_timestamp`; `source="csv"`.
- `eddn_market.py::write_buffers()`: pass the already-in-scope full
  `timestamp` (not truncated) as `data_timestamp`; `source="eddn"`.

A shared small normalization helper (mirroring `trade_routes.py::_parse_ts()`'s
approach but producing a normalized *string* rather than a `datetime`,
since the comparison happens in SQL, not Python) lives in
`persistence/repository.py` near `save_faction_snapshot()`, used by
every call site so the Unix-epoch-to-string and `Z`-vs-`+00:00`
normalization logic exists in exactly one place.

## Testing

- The normalization helper: synthetic tests — a journal-style `...Z`
  timestamp, an EDSM-style Unix epoch, and confirmation both produce the
  same normalized string for the same real instant, plus that two
  differently-formatted-but-equal instants compare equal after
  normalization.
- `save_faction_snapshot()`'s freshness guard: synthetic tests against a
  real (in-memory or temp-file) SQLite database — write an older row,
  attempt to overwrite with an even-older `data_timestamp`, confirm the
  original data survives untouched; write a newer row over an older one,
  confirm it does overwrite; write over a legacy `NULL`-timestamp row,
  confirm it always overwrites regardless of the new timestamp's value.
- No test for the individual call sites' plumbing (reading `evt.get("timestamp")`,
  `row.get("updated_date")`, etc.) — matches this codebase's existing
  convention of verifying pure logic directly and confirming UI/event
  wiring live.
