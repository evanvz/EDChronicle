# Squadron Server Reporting — Design

**Status:** Parked. Waiting to hear whether the squadron's Discord bot
takes the BGS-Tally API (server URL + API key) or a Discord webhook.
Build Part A if the answer is "API" and Part B if it's "webhook".

## Context

The squadron is asking every member to run BGS-Tally (an EDMC plugin),
which sends each member's BGS activity to the squadron's Discord bot
automatically, with nothing extra to do while playing. Members who
already run EDChronicle would otherwise need EDMC and BGS-Tally running
alongside it just for this.

Goal: EDChronicle can send the same data, in the same format, to the
same receiver, so the bot can't tell an EDChronicle member from a
BGS-Tally one.

**Scope and the "no third-party push" rule.** Normally EDChronicle
doesn't push data to other platforms (see project memory: no
Inara/Raven Colonial/EDSM uploads). This feature is a deliberate,
narrow exception the commander asked for:

- it only sends to a server the member's own squadron runs;
- it is opt-in per member and off by default;
- it never sends to a shared community platform.

Nothing in this design reaches any other service.

## How BGS-Tally does it

Verified against BGS-Tally's source (`bgstally/api.py` and
`bgstally/apimanager.py` on GitHub, `API_VERSION = "1.8.0"`).

### Member setup

- The member enters a **server URL** and an **API key**, with a switch
  each for activities, events and objectives.
- Nothing is sent until the member has **approved** the server
  (`user_approved`).
- If the server's discovered event list changes later, approval resets
  and the member must approve again.

### Headers on every request

- `apiversion: 1.8.0`
- `apikey: <key>`, only when a key is set. BGS-Tally strips the key to
  alphanumerics and caps it at 128 characters.

### Endpoints

All paths are relative to the base URL. The server can rename any of
them via discovery (below).

| Endpoint | Method | When | Payload |
|---|---|---|---|
| `discovery` | GET | on startup / settings change | none; the response configures the rest |
| `activities` | PUT | every 60 s (or the server's `min_period`, whichever is longer), only when activity changed since the last send | one activity object |
| `events` | POST | every 5 s (or `min_period`), when events are queued | a JSON list of up to 10 events (or the server's `max_batch`, whichever is larger) |
| `objectives` | GET | every 30 s (or `min_period`) | none; the response is a JSON list of objectives |

### Discovery response

This is optional. Any missing field falls back to the defaults below,
and an invalid response means "use all defaults".

```json
{
  "name": "…", "description": "…",
  "endpoints": {"activities": {"path": "activities", "min_period": 60},
                "events": {"path": "events", "min_period": 5, "max_batch": 10},
                "objectives": {"path": "objectives", "min_period": 30}},
  "events": {"MissionCompleted": {}, "MarketSell": {"filters": {"StarSystem": "^Ekono$"}}, …}
}
```

- An endpoint missing from `endpoints` is never called.
- Only event types listed in `events` are sent.
- A type's optional `filters` map field names to regexes; the event is
  sent only if every field matches.

**Default event list** (used when discovery gives none):
ApproachSettlement, CarrierJump, CommitCrime, Died, Docked,
FactionKillBond, FSDJump, Location, MarketBuy, MarketSell,
MissionAbandoned, MissionAccepted, MissionCompleted, MissionFailed,
MultiSellExplorationData, RedeemVoucher, SellExplorationData, StartUp,
SyntheticCZ, SyntheticGroundCZ, SyntheticCZObjective, SyntheticScenario.

### Event payload

Each event is the raw journal event, with these changes:

- **Removed:** every `*_Localised` key, at any depth.
- **Added to every event:** `cmdr`, `tickid`, `ticktime`.
- **Added only if missing:** `StationFaction: {"Name": …}`,
  `StarSystem`, `SystemAddress` and `timestamp`, filled in from current
  state.
- **`MarketBuy`:** gains `StockBracket` and `Stock`.
- **`MarketSell`:** gains `DemandBracket` and `Demand`.
- **`MissionFailed` / `MissionAbandoned`:** `StationFaction` is set to
  the mission's faction.
- **`Synthetic*` events** are BGS-Tally's own inventions, not journal
  events. It derives them for conflict zones and scenarios.

### Activity payload

One object per tick:

```json
{"cmdr": "…", "tickid": "…", "ticktime": "…", "timestamp": "…",
 "systems": [{"name": "Ekono", "address": 123, "twkills": {},
   "factions": [{"name": "Elite United Worlds", "state": "Boom", "influence": "0.43",
     "stations": [],
     "bvs": "…", "cbs": "…", "exploration": "…", "exobiology": "…",
     "infprimary": "…", "infsecondary": "…", "missionfails": "…",
     "murdersspace": "…", "murdersground": "…", "tradebm": "…", "scenarios": "…",
     "tradebuy":  {"low": {"items": 0, "value": 0}, "high": {…}},
     "tradesell": {"zero": {"items": 0, "value": 0, "profit": 0}, "low": {…}, "high": {…}},
     "czspace": {"low": 0, "medium": 0, "high": 0},
     "czground": {"low": 0, "medium": 0, "high": 0, "settlements": [{"name": "…", "type": "…", "count": 0}]},
     "sandr": {…}}]}]}
```

- Faction fields that are zero are **left out**, so sending only what
  we track is valid.
- `infprimary` / `infsecondary` are the summed mission influence
  (+ to +++++) for missions where the faction was the primary or a
  secondary faction.
- The Thargoid-war fields (`tw*`) are beyond scope and always omitted.

## Part A — API sender (build if the bot takes URL + key)

### Settings: new "Squadron Server" section

- **Server URL** and **API key** fields. The key is stored in the
  existing settings file and shown masked.
- **Test connection.** Calls `discovery` and shows the server's name,
  its description, which endpoints it offers and which event types it
  accepts, or the error.
- **Switches,** all off by default, and greyed out when the server
  doesn't offer them:
  - Send activity summary;
  - Send events;
  - Receive squadron objectives.
- **Location-revealing events** (Docked, FSDJump, Location,
  CarrierJump, ApproachSettlement, CommitCrime, Died) have their own
  switch, "Include location and crime events". It is off by default
  even when the server accepts them. With it off, those types are
  dropped before queueing.
- **Approve server button.** Required before anything is sent. It
  records the approved event list. If a later discovery returns a
  different list, approval is cleared and the settings page says why,
  matching BGS-Tally.
- **Preview.** Shows the JSON of the next activity send and the last
  queued events.
- **Status line:** "Last sent HH:MM", or the last error, e.g. "401 —
  check your API key".

### Sending (`edc/core/squadron_api.py`, a new module)

Pure functions, no Qt:

- `build_event(event, state, tick)` applies the event changes above.
- `build_activity(cmdr, tick, rows)` maps our tables to the activity
  object.
- `event_allowed(event, discovery, include_location)` applies the
  discovery list, the regex filters and the location switch.

One worker QObject on its own QThread, created once and kept for the
app's lifetime (project rule), with its own DB connection:

- It sends events every `max(5, min_period)` s and activity every
  `max(60, min_period)` s, and only when the activity changed.
- It fetches objectives every `max(30, min_period)` s.
- It uses `requests` with a timeout.
- A network failure keeps events queued (capped at 500, oldest dropped
  first) and retries at the next period. Nothing is ever retried in a
  tight loop.
- **Never during journal replay.** `main_window._replaying` is true
  while the journal is being bootstrapped, and events seen then are not
  queued. Otherwise every restart would re-send the whole session, the
  same double-count trap the session activity tables already guard
  against.
- On app close it is cancelled along with the other background workers
  on the shared shutdown deadline (commit 923632e). Unsent events are
  dropped, since the activity summary re-carries their totals.

### Mapping our data to the activity object

Scope is "since the last BGS tick" (`edc/core/bgs_tick.py`), the same
boundary as the Session BGS Activity Report
(`2026-09-25-session-bgs-activity-report-design.md`). `tickid` is the
tick timestamp string; BGS-Tally uses its tick service's id, and the
receiver treats it as an opaque key.

| Activity field | Our source | Status |
|---|---|---|
| `infprimary` / `infsecondary` | `faction_mission_completions` (`influence_tier`, `is_primary`) | have |
| `missionfails` | MissionFailed events | needs a small counter table |
| `bvs` / `cbs` | vouchers recorded at cash-in (commit 2114059) | have |
| `exploration` | exploration data sales credited to the station owner | verify at build time (the SINC alignment may have changed what is recorded) |
| `exobiology` | SellOrganicData, credited to the station owner | verify at build time (SINC says it doesn't count for BGS; BGS-Tally still sends it) |
| `tradesell` / `tradebuy` by bracket | `faction_trade_sold` plus the trade-purchase recording (commit 10f9f34); demand/stock bracket from `market_prices` | check the brackets are stored; add them if not |
| `tradebm` | black-market sales | skip in v1 (field omitted) |
| `czspace` / `czground` | conflict-zone detection | skip in v1 unless the session report already records CZ wins |
| `murdersspace` / `murdersground` | CommitCrime murder events | skip in v1 |
| `state`, `influence` | latest `faction_snapshots` for the system | have |
| `sandr`, `scenarios`, `tw*` | none | omitted |

"Skip in v1" fields are simply left out, which is exactly what
BGS-Tally does for zero values. Nothing false is ever sent.

### Objectives (optional, v1.1)

Objectives received from the server are shown read-only in the BGS
Tasks tracker, under their own heading ("From squadron server"). They
are never merged into the member's own tasks.

## Part B — Discord webhook (build if the bot takes a webhook URL)

BGS-Tally also has a separate feature (`webhookmanager.py` /
`discord.py`) that posts formatted activity reports straight into a
Discord channel through a webhook, with no server in between. If
that's what the squadron uses:

- **Settings:** a webhook URL field and "Post my tick report"
  (off by default), plus a Test button that sends one test message.
- **Content:** the report text comes from the Session BGS Activity
  Report's data, formatted as a Discord message similar to
  BGS-Tally's.
- **When:** posted once after each tick and on demand ("Post now").
  The existing message is edited for the same tick rather than
  spamming new ones.
- **Research needed first:** BGS-Tally's exact message layout, so the
  squadron's channel looks consistent.

## Testing

- **Unit tests for the pure functions:**
  - `*_Localised` keys are removed at any depth, including inside lists;
  - the extra fields are added;
  - the MarketBuy/MarketSell bracket fields are added;
  - the discovery list and regex filters are applied;
  - location events are dropped when the switch is off;
  - zero fields are left out of the activity object;
  - the mission influence sum matches BGS-Tally's formula.
- **Worker test against a local mock server** (`http.server` in a
  thread):
  - discovery defaults apply when the server returns 404 or invalid
    JSON;
  - approval resets when the event list changes;
  - events are batched at `max_batch`;
  - activity is only sent when it has changed;
  - events are queued and kept while the server is down;
  - nothing is sent during replay.
- **Live check** (project rule: in-game confirmation): one member
  enables it against the squadron bot, plays one tick, and the squadron
  confirms the bot shows that member's activity the same way it shows a
  BGS-Tally member's.

## Open questions

1. Does the squadron bot take the API (URL + key) or a webhook? This
   decides Part A vs Part B.
2. If API: which event types does the bot's discovery list? We'll learn
   this from the first Test press.
3. Does the bot need a specific `tickid` format? BGS-Tally's tick
   source may differ from tick.edcd.io. Ask the bot's maintainer if
   ticks don't line up.
