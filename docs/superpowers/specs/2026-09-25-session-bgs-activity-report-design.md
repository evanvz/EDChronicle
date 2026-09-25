# Session BGS Activity Report — Design

## Context

Following a review of the BGS-Tally plugin's Discord activity report
(https://github.com/aussig/BGS-Tally/wiki), the commander asked for an
equivalent view in EDChronicle: a report of everything done this BGS
"session" (missions, combat bonds/CZ kills, exploration/trade data sold),
grouped by system and faction, across every system visited — not scoped
to one target faction the way the existing Faction Expansion tracker is.

Placement: a new, separate panel/window (not an extension of the Faction
Expansion tracker, which stays exactly as-is — it answers a different
question, "is my one targeted push working", not "what did I do this
session").

Session boundary: since the last detected BGS tick, matching BGS-Tally's
own "Activity after tick" framing. `edc/core/bgs_tick.py` already calls
the community tick.edcd.io service and returns a real ISO8601 tick
timestamp — this is the filter boundary (`>= tick_iso`), not app-launch
time or a manual reset. A tick can span hours and survive an app restart
or crash mid-session, so the underlying data must be persisted, not held
in memory only.

## Research

**Missions** are already fully covered: `faction_mission_completions`
(`persistence/database.py:276-297`, extended this session with
`is_primary`) already stores `system_address, faction_name, completed_at,
influence_tier, is_primary` for every faction a `MissionCompleted`'s
`FactionEffects` touches — not scoped to any one faction. No changes
needed here; the new report queries this table directly with
`completed_at >= tick_iso`.

**Combat bonds** (`FactionKillBond`) are faction-attributed today via
`AwardingFaction` (`event_engine.py:1027-1031`, building the in-memory
`state.active_combat_bonds` dict) but never system-attributed or
persisted — wiped on restart. `Bounty` vouchers carry `VictimFaction`
(who you killed), not an awarding faction — the game does not expose
which faction actually credits a bounty voucher at journal time (that's
determined by whichever station/faction you redeem it at, later,
separately) — bounties are excluded from the new per-faction combat
table for the same reason BGS-Tally's own report shows `.CBs` (combat
bonds) as a system-level figure, not per-faction.

**CZ kills** (`_credit_cz_kill`, `event_engine.py:363-403`) are already
inferred and faction-attributed via the same `AwardingFaction` field
(confirms a `FactionKillBond` landing inside a pending-CZ window), tallied
into `state.cz_kills[faction_name]` — again in-memory only, no system
dimension, wiped on restart.

**Exploration/trade data sold** has no faction attribution at all today.
`SellExplorationData`/`MultiSellExplorationData` (`event_engine.py:1406-
1407`) only zeroes a running total, doesn't even record the sale amount.
`MarketSell` (`:1081-1097`) tracks flat session totals
(`session_trade_revenue`/`session_trade_profit`) plus a single lump
`squadron_bgs_trade_cr`, gated by `_at_squadron_faction_station()`
(`:405-411`, checks `state.controlling_faction == squadron_faction_name`)
— not faction-keyed. Since selling only happens while docked, and
`state.controlling_faction` (from the current system's `Location`/
`FSDJump`/`Docked`) is already available at sale time, attributing a sale
to "the current system's controlling faction" needs no new lookup, just a
new per-sale record instead of one gated lump total.

**Session boundary / tick timestamp**: confirmed no existing concept of
"session start" anywhere in the app (`main_window.py`, `session_ledger.py`
— no `session_start`/`launch_time`/`reset(` found). `bgs_tick.py`'s
`fetch_latest_tick()` is the real answer, already wired into
`player_faction_panel.py:2032` (`set_latest_known_tick`) for the tick
countdown display elsewhere — this design reuses that same call, not a
new detection mechanism.

## Architecture

Three new tables, matching `faction_mission_completions`'s exact shape
and precedent (one row per event, system+faction+timestamp, queried with
a `>=` time filter — no session-reset logic needed anywhere, "session" is
purely a query-time filter against real timestamped rows):

```sql
CREATE TABLE faction_combat_bonds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    system_address INTEGER NOT NULL,
    faction_name   TEXT    NOT NULL,
    reward         INTEGER NOT NULL,
    earned_at      TEXT    NOT NULL
);

CREATE TABLE faction_cz_kills (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    system_address INTEGER NOT NULL,
    faction_name   TEXT    NOT NULL,
    zone_type      TEXT    NOT NULL,  -- 'ground' | 'space'
    size           TEXT    NOT NULL,  -- 'l' | 'm' | 'h'
    earned_at      TEXT    NOT NULL
);

CREATE TABLE faction_trade_sold (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    system_address INTEGER NOT NULL,
    faction_name   TEXT    NOT NULL,  -- controlling faction of the selling station
    kind           TEXT    NOT NULL,  -- 'commodity' | 'exploration' | 'exobiology'
    value          INTEGER NOT NULL,
    sold_at        TEXT    NOT NULL
);
```

Each gets one `record_*` method on `Repository`, called from a new
`main_window.py` hook at the same event the in-memory tally already
updates (`FactionKillBond`, `_credit_cz_kill`'s call site, `MarketSell`,
`SellExplorationData`/`MultiSellExplorationData`) — mirrors
`_record_faction_mission_completion`'s existing pattern exactly, wrapped
in the same try/except-log-and-continue shape. The existing in-memory
`state.active_combat_bonds`/`state.cz_kills` dicts are untouched — they
already serve their own current purpose (unredeemed-bond station
pointer, live CZ tally display) and aren't session/tick-scoped the same
way.

**Report query**: one new `Repository.get_session_activity_report()`
taking a `since` timestamp (the last known tick, fetched fresh via
`bgs_tick.fetch_latest_tick()` when the panel opens/refreshes, same
worker-thread pattern as every other network call in this app), querying
all four tables (`faction_mission_completions` plus the three new ones)
filtered `>= since`, grouped into `{system_name: {faction_name: {...}}}`
— one query per table, assembled in Python (four small queries, not one
complex JOIN — the four event types don't share a natural join key
beyond system+faction, and a JOIN would multiply rows across tables
rather than aggregate them).

**New panel** (`edc/ui/panels/session_activity_panel.py`, new file):
read-only, refresh button (re-fetches the tick + re-queries), one card
per system with mission/INF/combat/CZ/trade lines per faction — same
visual language as the existing Faction Expansion tracker's cards
(`_CARD_STYLE`, `_HDR_STYLE`), added to the main window's panel set the
same way `faction_expansion_dialog.py` was (a menu/button launch point,
not a permanently-docked tab, since this is a periodic-check report, not
something referenced every event).

## Testing

Each new `record_*` repository method: real-SQLite unit tests mirroring
`test_faction_mission_completions.py`'s shape (insert, read back,
scoped-by-system/faction, time-window filtering). Each new event-hook
method in `main_window.py`: fake-`self` unit tests mirroring
`test_record_faction_mission_completion.py`. `get_session_activity_report`:
real-SQLite test seeding all four tables and asserting the grouped
output shape. TDD throughout, per this session's established
git-stash-verify pattern. New panel: manual/live confirmation only (per
this project's own testing convention — UI features need live
in-game confirmation, not just green tests).
