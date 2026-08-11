# BGS Tick-Driven Refresh + Overview Flash — Design

## Context

Player Faction's daily full EDSM refresh currently triggers off a local
calendar-day boundary — an approximation of "once per BGS tick" (the
game's actual daily faction-state recalculation), since calendar days
and real tick times don't line up. `tick.edcd.io` publishes the actual
detected tick time, found by the user while browsing EDDN-adjacent
tooling. Two things requested: trigger the refresh off the real tick
instead of the calendar-day guess, and show a brief flash on the
Overview HUD when a tick is detected and the refresh kicks off.

## Research

Confirmed live (not just from docs): `GET https://tick.edcd.io/api/tick`
returns a bare JSON string, e.g. `"2026-08-11T10:51:03+00:00"` —
`response.json()` parses it directly to a Python `str`. No auth, no
rate limit documented, `Access-Control-Allow-Origin: *`. Ticks happen
"once or twice per day" per the service's own docs, at no fixed clock
time — genuinely variable, unlike a calendar-day boundary.

The service has no next-tick prediction endpoint, only historical
detection — confirmed via its docs (`/api/tick`, `/api/ticks`, and a
Socket.IO WebSocket for live push, no forecast of any kind). A "next
tick" HUD element was explicitly ruled out for this reason: inventing
our own prediction from irregular historical data would present a
guess as fact for something players might plan real gameplay around.

Chose polling over the available WebSocket push option specifically
because this session already root-caused a real production bug in a
different persistent connection (the EDDN ZMQ listener silently
stalling with no error — see today's `eddn_listener.py` fix, the
`_STALE_CONNECTION_TIMEOUT_S` watchdog) — adding a second long-lived
external connection with the same failure class, before that fix has
even been running long enough to trust, was judged not worth the
"instant instead of a few minutes' delay" benefit. Polling means every
check is a fresh, stateless request — the same shape as the
EDSM/EDDN-publish calls that have been reliable all session.

`player_faction_panel.py::_start_refresh_all()` already does everything
the tick-driven trigger needs (worker thread, progress reporting,
cancel button, per-day dedup against already-fresh systems) — confirmed
by reading it directly. The only missing piece is a second trigger path
into it, alongside the existing calendar-day one
(`_maybe_auto_refresh_all()`), which stays completely unmodified.

`overview_panel.py` already has a fade-in/out pattern
(`QGraphicsOpacityEffect` + `QPropertyAnimation` on `overview_actions`,
lines 268-273 and around 562) used when new Action-line content
arrives — the flash reuses this exact mechanism rather than inventing a
new one.

## Design

**`edc/core/bgs_tick.py`** (new) — one function:

```python
def fetch_latest_tick() -> Optional[str]:
    """Returns the most recently detected BGS tick as an ISO8601 UTC
    timestamp string (e.g. "2026-08-11T10:51:03+00:00"), or None on any
    failure -- network error, timeout, bad/unexpected response shape.
    Call from a worker thread only, never the UI thread."""
```

Plain `requests.get`, identifying `User-Agent` (matching this session's
established convention for every other outbound HTTP call), 10s
timeout. A non-string or empty response body counts as failure (`None`),
same defensive shape as `edsm_faction_lookup.py`'s response validation.

**`edc/core/faction_refresh_tracker.py`** — two new methods on
`FactionRefreshTracker`, same `faction_refresh.json` file, new key
`"last_refreshed_tick"`:

```python
def last_refreshed_tick(self) -> Optional[str]: ...
def mark_refreshed_tick(self, tick_iso: str) -> None: ...
```

Plain string storage/comparison (no datetime parsing needed — the tick
service's own timestamp is compared for equality only, never
arithmetic on it).

**`edc/ui/panels/player_faction_panel.py`** — new public method:

```python
def maybe_refresh_for_tick(self, tick_iso: Optional[str]) -> None:
    """Called periodically from MainWindow with the latest result of
    fetch_latest_tick() (None if the fetch failed this round -- the
    existing calendar-day startup check, _maybe_auto_refresh_all(),
    remains the fallback for that case, unmodified). Starts the full
    refresh only if tick_iso is a genuinely new tick we haven't already
    refreshed against."""
```

- No-op if `tick_iso is None`, or equals `self._refresh_tracker.last_refreshed_tick()`,
  or `not self._faction_name`, or a refresh is already running (same
  guard `_start_refresh_all()` itself already checks).
- Otherwise: stores `tick_iso` on `self._pending_tick`, emits a new
  `tick_refresh_started = pyqtSignal()` on the panel, and calls
  `self._start_refresh_all()`.
- `_on_refresh_all_finished()` gains one addition: if
  `self._pending_tick` is set, call
  `self._refresh_tracker.mark_refreshed_tick(self._pending_tick)` and
  clear it — mirrors the existing `mark_refreshed()` call already there,
  so an interrupted refresh (app closed mid-way) never marks the tick
  as handled, same interrupted-refresh semantics the calendar-day path
  already relies on.

**`edc/ui/main_window.py`** — new `QTimer` (10-minute interval, matching
the existing `_player_faction_refresh_timer`'s order of magnitude) plus
a small `QObject` worker on its own `QThread` (same shape as every
other periodic background check in this file — `_EddnFlushWorker` etc.):
calls `fetch_latest_tick()` off the UI thread, emits the result (`str`
or `None`) back to the main thread, which calls
`self.player_faction_panel.maybe_refresh_for_tick(result)`.

**`edc/ui/panels/overview_panel.py`** — a small one-line `QLabel`
(e.g. "Tick detected — updating BGS data…") placed near the top of the
panel, with its own `QGraphicsOpacityEffect`, connected to the new
`tick_refresh_started` signal: fades in, holds ~10s, fades out. Fully
separate widget/effect from the existing Action-line fade — reuses the
*pattern*, not the same effect instance (they animate independently and
could otherwise overlap).

## Testing

- `fetch_latest_tick()`: synthetic tests with a mocked `requests.get`
  — valid string response, non-200 status, malformed/non-string body,
  timeout/connection error — all asserting the correct `str`/`None`
  result. No live network call in the test suite itself (matches this
  session's existing test conventions — `test_eddn_commodity.py` etc.
  don't hit real network either).
- `FactionRefreshTracker`'s two new methods: synthetic round-trip test
  (write, read back, confirm persists alongside the existing
  `last_refresh`/`last_csv_import` keys without clobbering them).
- `maybe_refresh_for_tick()`: synthetic tests covering each no-op
  branch (`None` input, unchanged tick, no faction known, refresh
  already running) plus the "new tick starts a refresh and emits the
  signal" path — using the same lightweight construction approach
  already established for testing `EddnPublisher` in
  `test_eddn_commodity.py` (construct the object directly, no full app
  bootstrap).
- The `QTimer`/worker wiring in `main_window.py` and the Overview flash
  itself: no automated test, consistent with this session's established
  project convention that journal/UI-integration features are verified
  live in-game, not unit tested (there are no existing tests touching
  `main_window.py` or any panel file at all). Live verification: leave
  the app running past a real detected tick (or trigger manually by
  clearing `last_refreshed_tick` from `faction_refresh.json` and
  waiting for the next timer fire) and confirm the flash appears and a
  refresh starts.
