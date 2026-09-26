# BGS Tasks Tracker — Design

Date: 2026-09-26
Status: approved in chat (input method, location, targets), awaiting spec review

## Problem

The squadron posts its BGS objectives as a short prioritised list (system +
action: Boost faction X, Vote for X vs Y, Fight for X vs Y, PowerPlay
acquisition %, undermining notes). Today a commander has to keep that list
in their head and cross-check it against several EDChronicle panels to see
whether they've done their part this tick and whether the objective is
moving the right way. Most of what's needed to track each task is already
collected by the app; only the task list itself is missing.

## Scope

- Tasks are entered manually: system name + task type + faction (+
  opponent for Vote/Fight). No parsing of the Discord post (possible later,
  not v1).
- A "BGS Tasks…" button in the Player Faction panel (next to Faction
  Expansion Tracker and Session BGS Activity) opens a dialog listing all
  tasks with live progress.
- A one-line hint on the Overview HUD when the player is in a system that
  has a task.
- Boost tasks show progress against the squadron guide's per-tick limits,
  with defaults editable in Settings and labelled as squadron guidance, not
  Frontier numbers.

Out of scope for v1: Discord paste import, per-system PowerPlay merit
tracking, multi-commander/shared task lists, pushing tasks anywhere (no
third-party data push).

## Task types

| Type | Fields | Progress shown | Data source |
|---|---|---|---|
| Boost | system, faction | Your signed tier score, bounties, combat bonds, trade profit, exploration and exobiology for that faction in that system since the last tick; the faction's influence in the latest snapshot vs the previous day's | `get_session_activity_report(since_tick)` filtered to system+faction; `faction_snapshots` |
| Vote (election) | system, faction, opponent | Days won (e.g. 2 - 0) and status; your missions, trade profit and exploration for the faction; a warning if you log combat bonds/CZ kills there | `net.system_bgs_status` conflicts (after the election change below); session report |
| Fight (war/civil war) | system, faction, opponent | Days won and status; your CZ kills, combat bonds cashed and missions for the faction; a warning if you cash bonds for the opponent | `net.system_bgs_status`; session report |
| PowerPlay | system, note | Latest PowerPlay state/progress for the system | `systems.pp_*` via `get_system_powerplay_snapshot()` (your own last visit; no CSV fallback in v1) |
| Note | system (optional), free text | Text only | — |

Freshness: every conflict/influence/PowerPlay value shows its age
("updated 3h ago"), same as the Faction Expansion Tracker.

### Boost limits (squadron guidance)

Defaults from the squadron guide, editable in Settings:

| Stream | Default per tick |
|---|---|
| Mission tier score (INF+) | 25 |
| Bounties cashed | 20,000,000 CR |
| Exploration data sold | 20,000,000 CR |
| Trade profit | no limit, shown raw |

Shown as "18 / 25" with a bar; turns amber past the limit with the text
"past squadron limit — diminishing returns". The dialog footer says the
limits come from squadron guidance.

## Task status

Each task card shows one status line:

- **Done this tick** — Boost: any stream reached its limit. Vote/Fight: you
  logged at least one relevant action for the faction this tick.
- **To do** — nothing logged this tick.
- **Losing ground** — Vote/Fight: opponent has more days won than the
  faction. Boost: influence dropped since the previous snapshot.
- **Conflict ended** — Vote/Fight: the system has been read since the task
  was created and the conflict is no longer in it. Ended conflicts are
  cleared by the player's own journal visit (EDDN/EDSM readings never
  clear, since they don't reliably carry the full picture). The task stays
  until removed.

Tasks persist until the user removes them (no auto-delete). Order is the
user's priority order (drag or up/down), matching the squadron post.

## Storage

New personal-DB table (backed up with the rest of the personal data):

```sql
CREATE TABLE IF NOT EXISTS bgs_tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    system_address INTEGER,          -- resolved from the entered name; NULL if unknown yet
    system_name    TEXT    NOT NULL, -- as entered/resolved
    task_type      TEXT    NOT NULL, -- boost / vote / fight / powerplay / note
    faction_name   TEXT,
    opponent_name  TEXT,
    note           TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);
```

System name entry uses autocomplete over known system names and resolves to
`system_address`. An unresolved name is still saved (NULL address) and
resolved the first time a system with that name is seen; the card shows
"no data yet" until then.

Faction/opponent fields autocomplete from factions known for that system
(`faction_snapshots`), free text allowed.

Boost limits are stored in the existing config (`edc/config.py`), not the
DB.

## Required change: store elections

`net.system_bgs_status` currently keeps only War/CivilWar conflicts, so
Vote tasks in other systems would have no days-won data. Elections will be
stored too, and the Combat System Status panel's "War / Civil War" filter
and conflict text will explicitly exclude `war_type == "election"` so that
panel is unchanged.

## Overview HUD hint

When `state.system_address` matches a task, one line under the existing
system header, e.g.:

`Squadron task: Boost Elite United Worlds — tier score 18/25`
`Squadron task: Vote Remnants of the Code vs Elite United Worlds — 2-0`

Multiple tasks in one system are joined with " · ". Hidden when there's no
task for the current system.

## Refresh

The dialog refreshes when opened and on the same live-push signals the
Session BGS Activity Report and Faction Expansion Tracker already use
(mission completion, voucher cash-in, sale, EDDN flush), plus the
existing periodic refresh. No new timers.

## Testing

- Repository: task CRUD, ordering, name resolution, per-task progress
  aggregation from seeded session-report tables and snapshots.
- Status rules: one test per status for each task type.
- Elections: stored in `net.system_bgs_status`; Combat System Status
  output unchanged for a system with only an election.
- Dialog/HUD: render tests with fake data, same pattern as
  `test_session_activity_dialog_render.py`.
- Live check (project rule): enter the current squadron objectives,
  complete a few actions in-game, confirm the cards and HUD line update.
