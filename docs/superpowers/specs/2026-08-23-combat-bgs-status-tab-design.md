# Combat / BGS-Combat Status Tab — Design

## Context

Following a PC migration, the commander asked whether EDChronicle could
surface which systems currently have an active War/CivilWar, which
factions are sitting in multiple simultaneous BGS states (e.g.
War+Outbreak), and which systems have RES/Low RES/High RES/Hazardous RES
sites present — all within a radius of the player's current location, the
same shape as the existing Market/Mining/Trade-Route-Loop-Planner
searches. Restore/mining/massacre mission board contents were also asked
about, but are not retrievable for any system other than the one the
commander is physically viewing a mission board in — EDDN has no missions
schema at all (confirmed against the full schema list at
https://github.com/EDCD/EDDN/tree/master/schemas: approachsettlement,
blackmarket, codexentry, commodity, dockingdenied, dockinggranted,
fcmaterials_capi, fcmaterials_journal, fssallbodiesfound, fssbodysignals,
fssdiscoveryscan, fsssignaldiscovered, journal, navbeaconscan, navroute,
outfitting, scanbarycentre, shipyard — no `missions` entry). That request
is out of scope for this design; only War/CivilWar, multi-state factions,
and RES tiers are covered here.

Placement: a new sub-tab under the existing Combat tab, alongside the
current Combat contacts/bounty/fine/massacre/CZ view (which becomes an
"Overview" sub-tab).

## Research

**War/CivilWar and multi-state factions** are already present, per-system,
on the `Conflicts` and `Factions[].ActiveStates/PendingStates/
RecoveringStates` fields of `Location`/`FSDJump`/`CarrierJump`/`Docked`
journal events — confirmed live in the commander's own journal
(`Journal.2026-08-23T102557.01.log:57`, a `Location` event for HIP 22052
carrying both a `Conflicts` array with an election WarType and per-faction
`RecoveringStates`). The app already parses this shape for the *current*
system only (`edc/core/bgs_conflicts.py`, `event_engine.py:471-477`
building `state.factions`/`state.system_conflicts`). The same fields ride
EDDN's `journal` schema verbatim — EDDN's listener
(`edc/core/eddn_listener.py`) already subscribes to that schema and
already parses `Factions` network-wide, but only for a squadron-watched
faction name (`_maybe_emit_faction_seen`, gated behind
`self._watched_factions`). Extending that same message-handling path to
also emit `Conflicts`/multi-state `Factions` unconditionally (not gated by
watched-faction) is a small, well-contained addition — no new EDDN
subscription needed, since the listener's single ZMQ SUB socket already
receives all schemas and filters client-side by `$schemaRef`.

**RES/Low RES/High RES/Hazardous RES** signals are present per-system on
`FSSSignalDiscovered` (`SignalType:"ResourceExtraction"`, with the tier
encoded in `SignalName_Localised` — confirmed live: `"Resource Extraction
Site"` (nominal), `"Resource Extraction Site [Low]"`,
`"...[High]"`, `"...[Hazardous]"`, all four seen in the commander's own
journal). No ring/body granularity — signal is system-level only. The app
already ingests `FSSSignalDiscovered` for its "system signals" list
(`event_engine.py:1401-1447`, `_classify_system_signal` at line 217), but
has no case for `SignalType == "ResourceExtraction"` — it falls through to
the generic `"Other"` bucket today, even for the player's own scans.
EDDN has a dedicated `fsssignaldiscovered` schema (confirmed against
EDDN's schema list) carrying a `signals` array per system per message —
the listener does not currently subscribe to it at all (only
`journal`/`commodity`/`fcmaterials_journal` schema prefixes are checked in
`_pump()`), but the same always-on ZMQ socket already receives this
traffic, so "subscribing" is really just adding a third schema-prefix
branch to the existing dispatch, not a new network connection.

**Storage precedent**: `faction_snapshots`/`market_prices` both use a
freshness-guarded upsert (`ON CONFLICT ... WHERE excluded.data_timestamp
>= <table>.data_timestamp`, see `repository.py::save_faction_snapshot`) so
whichever pipeline (own journal vs EDDN) has the more recent underlying
data wins, regardless of write order. The same idiom is reused here.

## Design

### Schema — two new tables, "latest-known-per-system" shape

Not a daily-history table like `faction_snapshots` — for a live
war/RES-status tool, only the current status matters, and a war typically
resolves within about a week of `WonDays` accumulating, so multi-day
history would just be noise to filter back out. One row per system,
upserted in place.

```sql
CREATE TABLE IF NOT EXISTS system_bgs_status (
    system_address INTEGER PRIMARY KEY,
    system_name    TEXT,
    conflicts      TEXT,   -- JSON: [{faction1, faction2, war_type, status, won_days1, won_days2}]
    faction_states TEXT,   -- JSON: [{name, faction_state, active_states, pending_states, recovering_states, is_controlling}]
    data_timestamp TEXT,
    source         TEXT    -- 'journal' | 'eddn'
);

CREATE TABLE IF NOT EXISTS system_res_sites (
    system_address INTEGER PRIMARY KEY,
    system_name    TEXT,
    tiers          TEXT,   -- JSON: ["Nominal","Low","High","Hazardous"] (subset present)
    data_timestamp TEXT,
    source         TEXT
);
```

Only written when there's something to show: `system_bgs_status` is
skipped when there are no War/CivilWar conflicts *and* no faction has any
active/pending/recovering state; `system_res_sites` is skipped when no RES
signal was seen. This keeps both tables' row counts bounded to the
(small) fraction of the galaxy that's actually combat/BGS-relevant right
now, rather than one row per system ever visited.

Added to `persistence/database.py::run_migrations()`'s existing
`CREATE TABLE IF NOT EXISTS` list (same list `rings`/`spansh_bodies`/etc.
already live in) — no `_REQUIRED_SCHEMA_VERSION` bump, since that bump
exists specifically to force a full journal re-import for tables backfilled
*from* journal history, and these two tables are deliberately NOT
backfilled from old journal files (a war recorded in a month-old journal
entry is very likely already resolved — showing it as current would be
actively misleading). Both tables only ever accumulate from this point
forward (live journal tail + EDDN), consistent with the "current status,
not history" framing above.

### Retention — freshness badge, not row deletion

One row per system (not one row per day) is already cheap to keep
indefinitely — no deletion needed. Instead, age is surfaced in the UI from
`data_timestamp`, same pattern the existing CSV-stale banner already uses
(`player_faction_panel.py`'s `_CSV_STALE_DAYS = 7`): green ≤2 days, amber
2–7 days, red >7 days, and rows older than `_MARKET_DATA_MAX_AGE_DAYS`-
matching 14 days are filtered out of search results entirely (same cutoff
`market_prices` search already uses, `repository.py:14`) since a two-week-
old "War" entry is more likely wrong than right.

### RES tier parsing — shared helper, both pipelines

New tiny module `edc/core/res_signals.py`:

```python
"""Shared RES-tier parsing for FSSSignalDiscovered's ResourceExtraction
signals — used by both the live event engine (own journal) and
eddn_listener.py (network-wide), so the two can't drift."""
from __future__ import annotations

import re

_TIER_RE = re.compile(r"\[(Low|High|Hazardous)\]", re.IGNORECASE)


def res_tier_from_signal_name(signal_name: str) -> str:
    """'Resource Extraction Site [Hazardous]' -> 'Hazardous'.
    A plain 'Resource Extraction Site' (no bracket) -> 'Nominal'."""
    if not isinstance(signal_name, str):
        return "Nominal"
    m = _TIER_RE.search(signal_name)
    return m.group(1).title() if m else "Nominal"
```

### Own-journal path

- `event_engine.py::_classify_system_signal` gains a
  `SignalType == "resourceextraction"` case returning `"RES"`.
- The `FSSSignalDiscovered` handler (`event_engine.py:1401-1447`) stores a
  `"Tier"` field on the signal entry via `res_tier_from_signal_name()`,
  populated only when `Category == "RES"`.
- `main_window.py` gains `_save_system_bgs_status()` (mirrors
  `_save_faction_snapshots()`, reads `state.system_address`,
  `state.system`, `state.factions`, `state.system_conflicts`,
  `state.factions_timestamp`) called from the same
  `if name in ("Docked", "FSDJump", "Location")` block
  `_save_faction_snapshots` already lives in (`main_window.py:2239-2240`).
- `main_window.py` gains `_save_system_res_tiers()` (reads
  `state.system_address`, `state.system`, `state.system_signals` filtered
  to `Category == "RES"`) called on `name == "FSSSignalDiscovered"`.

### EDDN path

- `eddn_listener.py`'s `EddnPowerPlayWorker` gains two signals:
  `bgs_status_seen(id64, StarSystem, conflicts: list, factions: list,
  timestamp: str)` and `res_signal_seen(id64, StarSystem, tiers: list,
  timestamp: str)`.
- A new unconditional (not squadron-gated) `_maybe_emit_bgs_status(msg,
  timestamp)` runs for every relevant journal message, alongside the
  existing squadron-gated `_maybe_emit_faction_seen` call — filters
  `Conflicts` to `WarType in ("war", "civilwar")` and `Factions` to those
  with any non-empty active/pending/recovering state, emits only if either
  list is non-empty.
- `_pump()` gains a third schema branch for
  `https://eddn.edcd.io/schemas/fsssignaldiscovered/`, extracting
  `SystemAddress`/`StarSystem`/`signals[]` and calling a new
  `_maybe_emit_res_signal(msg)` that uses `res_tier_from_signal_name()` on
  each `SignalType == "ResourceExtraction"` entry.
- `eddn_market.py`'s `EddnMarketCache` gains two more buffers
  (`_bgs_status_buffer`, `_res_sites_buffer`, both keyed by
  `system_address` for same-flush-window dedupe) and two more slot
  methods; `pop_buffers()`/`flush()`/`write_buffers()` all grow from a
  7-tuple to a 9-tuple, threaded through `main_window.py`'s
  `_EddnFlushWorker` and `_on_market_flush_tick()` the same way the
  existing seven already are.

### UI

New file `edc/ui/panels/combat_bgs_status_panel.py`, self-contained like
`market_panel.py` (owns its own repo reference, radius `QSpinBox`, search
button, background search worker with its own DB connection). Columns:
System | Distance | War/CivilWar | Faction States | RES Tiers | Age.
Radius selector matches Market's (`QSpinBox`, 10–5000 ly, default 100,
`" ly"` suffix). Rows where a conflict faction, a multi-state faction, or
the squadron's own minor-faction/PowerPlay-power name is present are
highlighted (accent background), same visual language Trade Opportunities
already uses for squadron-relevant rows.

`combat_panel.py` (currently a single flat `QWidget`) gets restructured:
its existing content moves into an inner `QTabWidget`'s first tab
("Overview"), with the new panel as a second tab ("System Status").
`CombatPanel.refresh(state)` forwards to both sub-panels.

## Non-Goals

- Restore/mining/massacre mission board contents for systems not
  currently being viewed in-game — not retrievable via EDDN or the
  journal at all (see Context).
- Ring/body-level RES location — the signal is system-level only.
- Historical war/RES trend charts — only current status is stored.
