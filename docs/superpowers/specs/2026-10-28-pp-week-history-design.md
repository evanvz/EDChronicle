# PowerPlay week history — design

Date: 2026-10-28. Status: draft, awaiting Evan's approval.

## Intent

**The need.** Evan jumped into Ys and saw undermining, with no other power present. He wanted to know how the system's PowerPlay picture had moved since the weekly reset: undermining (U) and reinforcement (R) going up or down, control progress, and any state change. The app showed one current number, not a trend.

**Success.**
- Arriving in a system shows at a glance whether an attack is speeding up, slowing or has stopped.
- The watch list shows which watched systems were hit in the last 24 hours.
- Selecting a system on the watch list shows how the week went, day by day.

**Non-goals.**
- No history before the current cycle. The window is the weekly reset (Thursday 07:00 UTC) until now.
- No forecasting or end-of-cycle projection (that belongs to the parked Vulnerable/at-risk idea).
- No new data sources beyond the app's own history and EDDataHub.
- No changes to how the app records readings.

**Anti-goals** (failures even if it technically works):
- Showing 0 for a day nobody reported. A day without a report shows "—".
- Blocking the UI on a hub call.
- Breaking when the hub isn't configured or isn't reachable. A public install has no hub.

## What Evan decided

- **Window:** since the last weekly reset.
- **PowerPlay status card** (PowerPlay window, Status tab, current system): a small chart of U and R from the reset until now. Mockup option B in `.superpowers/brainstorm/1407-1793006941/content/status-week.html`.
- **Watch list** (PowerPlay window, Watch List tab):
  - one extra column per row, showing U gained in the last 24 h with an up or down arrow;
  - a day-by-day table (U, R and progress per day) for the selected row (mockup option C), shown below the list;
  - a row click still copies the system name.
- **Data:**
  - the app's own `pp_control_history` comes first;
  - EDDataHub fills the gaps;
  - it must work without the hub.
- **Build timing:** Wednesday 2026-10-28.

## Existing pieces

- **`pp_control_history`** (app SQLite, `persistence/database.py`).
  - Columns: `system_address`, `observed_at`, `pp_state`, `reinforcement`, `undermining`, `control`, `source`.
  - `Repository.record_pp_control` stores a reading only when it is newer than the latest stored one and differs from it.
  - Fed by the journal (systems Evan visits) and by EDDN for watch-list systems (`main_window._on_eddn_control`), but only while the app runs.
- **`bgs_tasks.control_status` / `watch_rows`.** These compute this cycle's R/U, split into decay and real attack, per watched system. The week start comes from `powerplay_week_start()`.
- **EDDataHub `observation_history`.**
  - Every `powerplay` fact from EDDN is stored, one row per report: `fact_type='powerplay'`, `system_id64`, `event_time`.
  - `value` holds the journal keys `PowerplayState`, `PowerplayStateControlProgress`, `PowerplayStateReinforcement` and `PowerplayStateUndermining`.
  - Full history is kept 14 days (`maintain.KEEP_FULL`), so a whole cycle is always there.
- **EDDataHub web API** (`eddatahub/web.py`).
  - Pattern to copy: `/api/system-factions?ids=`, which takes at most 100 ids and answers 503 when the database is unreachable.
  - Client pattern: `edc/core/eddatahub_client.py` (`fetch_system_factions`). It returns None when the hub isn't reachable and logs at info level.
- **Watch list UI.** `edc/ui/panels/powerplay_watch_panel.py`: a `QTableWidget` with `_COLUMNS` and the `_NumItem` sort helper.
- **Status card.** `edc/ui/panels/powerplay_panel.py`, `PowerplayPanel.refresh(state)`. It builds the conflict banner from `state` (current system's R, U, state and progress). `state.system_address` is the current system.

## Design

### Hub: `GET /api/system-powerplay?ids=<id,...>&since=<ISO>`

- **Returns** every `powerplay` report for the given systems with `event_time >= since`, oldest first, as `[{"system": id64, "time": ISO, "state": str|null, "reinforcement": int|null, "undermining": int|null, "control": float|null}]`.
- **Limits:**
  - at most 100 ids;
  - `since` must be an ISO time with a zone (400 otherwise);
  - `since` is clamped to at most 14 days back.
- **Errors:** 503 when the database is unreachable, like the other routes.
- **One row per report.** The hub keeps several sources per system; the response is all of them, by time.

### App client: `eddatahub_client.fetch_system_powerplay(base_url, addresses, since)`

- **Returns** `{id64: [reading, ...]}`, or None when the hub isn't configured, isn't reachable, or answers with something that isn't a list.
- **Readings** use the same keys as `pp_control_history` rows (`observed_at`, `pp_state`, `reinforcement`, `undermining`, `control`, `source="hub"`), so app and hub readings merge without conversion.
- **Batching:** 100 ids per request.

### Core: `edc/core/pp_week.py` (pure functions, no Qt, no I/O)

- **`merge(local, hub)`.** Takes one system's readings from both sources and returns them sorted by `observed_at`. Exact duplicates (same time and values) appear once.
- **`daily(readings, week_start, now)`.** Returns one entry per UTC day from the reset day to today: `{"day": date, "u": delta|None, "r": delta|None, "control": last|None, "state": last|None}`.
  - A day's delta is that day's last reading minus the previous day's last reading.
  - For the reset day, the delta is measured from 0, since R and U reset at the weekly tick.
  - A day with no reading has `u`, `r`, `control` and `state` all None.
  - If the day before had no reading, the delta is measured from the most recent earlier reading in the cycle, and the day is flagged `"spans": n_days` so the UI can mark it.
- **`last_24h(readings, now)`.** Returns `(gained, direction)`:
  - `gained` is the latest U minus U at the latest reading at least 24 h old within the cycle;
  - `direction` is "up", "down" or "flat";
  - returns None when there is no reading at least 24 h old in the cycle, or no reading in the last 24 h.
- **Undermining includes the weekly decay** set at the reset (see `control_status`). The chart and table show U as reported; they don't split out decay.

### Fetch and caching (app)

- **Background only.** Hub calls run on a background `QThread` worker, kept as an attribute so it stays in scope (project rule), with its own Database if it touches SQLite (project rule).
- **Status card:** on arrival in a system (when the current system address changes), read local readings since the reset and request hub readings for that one system. Draw the local data at once, then redraw when the hub answers.
- **Watch list:** on `refresh()`, request hub readings for all watched systems in one batched call. The 24 h column and the day table use the merged data. Before the hub answers, they use local data only.
- **Cache:** hub answers per system for 10 minutes, so tab switches and refreshes don't re-ask.
- **No hub stored in SQLite.** Hub readings are merged in memory and not written to `pp_control_history`. `record_pp_control` rejects out-of-order readings anyway.

### UI

- **Status card chart:** a small `QWidget` that paints with `QPainter`.
  - Size: about 90 px high, full card width.
  - Lines: U in red (`#FF6B6B`) and R in blue (`#4D96FF`), as step lines from the reset to now.
  - Axis labels: day names along the x-axis. The latest U and R values sit at the right end.
  - Shown under the existing PowerPlay conflict banner when the current system has a controlling power and at least one reading this cycle. Hidden otherwise.
  - A caption line: "N reports this week · last <age> ago".
- **Watch list column "U 24 h":**
  - Shows "+12,345 ↑", "— ↔" or "—" (no comparison point).
  - Sorts by number, with `_NumItem`.
  - Red when it rose.
- **Watch list day table:** a second, small `QTableWidget` below the list. It shows the selected row's `daily()` result, with columns Day, U, R, Progress and State.
  - A row for a day with no reading shows "—".
  - A day that spans gap days shows its delta with a "*" and the tooltip "change since <day>".
  - The table is hidden when no row is selected.

## Constraints

- One SQLite connection per thread; QThreads stay in scope (project CLAUDE.md).
- No schema change in the app's SQLite.
- The hub route is read-only and goes out on the existing deploy (`update.sh`).
- Hub data is LAN only. Nothing goes to third parties.
- The app's log times are local (UTC+2); hub and EDDN times are UTC. All new code works in UTC and shows local times only in the UI.

## Testing

- **Hub:** a route test for `/api/system-powerplay` (400 on a bad `since`; ids capped at 100), following `tests/test_web.py`. The DB query is tested the way `test_bgs.py` does, skipped without a database.
- **App core:** `pp_week` unit tests:
  - merge de-duplication;
  - a reset-day delta from 0;
  - a gap day showing None;
  - a delta spanning gap days;
  - `last_24h` with and without a comparison point.
- **App client:** a local HTTP server test, like `tests/test_eddatahub_markets.py`, including hub-unreachable returning None.
- **UI:** the app starts. The watch list shows the new column, and the day table appears for a selected row. Live confirmation in game, in Ys, by Evan.

## Calls made in writing this (Claude's, for Evan to check)

- **Reset-day undermining is mostly decay.** The reset-day U delta includes the weekly decay set at the reset. That cell gets a tooltip, "includes the weekly decay set at the reset", so it isn't read as an attack.
- **Day boundaries** are UTC days. The reset day runs from Thursday 07:00 UTC to midnight UTC. Times in the table and chart are shown in local time.
- **Hub URL for the PowerPlay window.** `PowerplayPanel` and the watch panel get the hub URL the way `player_faction_panel.eddatahub_url` does: an attribute set by `MainWindow` from config `eddatahub_url`, empty meaning no hub.
- **Hub-only readings** count as readings for "last <age> ago" and for the day table.

## Left to the builder

- The exact chart padding, fonts and label placement, within the app's existing dark styling (`edc/ui/style.py`).
- Whether the day table sits in a splitter or a fixed-height area.
- The worker class names and the signals used to hand hub results back to the UI thread. They must be bound-method slots, not lambdas, so the slot runs on the UI thread.
