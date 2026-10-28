# PowerPlay Week History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show how each system's PowerPlay reinforcement and undermining moved since the weekly reset: a chart on the PowerPlay Status tab, a "U 24 h" column on the Watch List, and a day-by-day table for the selected watch row.

**Architecture:**
- EDDataHub gets a read-only `/api/system-powerplay` route over `observation_history`.
- EDChronicle merges those readings in memory with its own `pp_control_history` rows. Pure functions in `edc/core/pp_week.py` compute the daily changes and the 24 h change.
- Hub calls run on a background QThread worker with a 10-minute cache.
- The UI draws local data at once and redraws when the hub answers.

**Tech Stack:**
- EDDataHub: Python 3.14, psycopg, stdlib `http.server`; tests use the `.venv` pytest.
- EDChronicle: Python 3.12, PyQt6, SQLite, requests, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-pp-week-history-design.md`

## Global Constraints

- **Window:** the current cycle only, from `bgs_tasks.powerplay_week_start()` (Thursday 07:00 UTC) until now.
- **No reading on a day:** show "—", never 0.
- **Never block the UI on a hub call.**
- **Everything works when `eddatahub_url` is empty or the hub is unreachable,** using local data only.
- **One SQLite connection per thread. QThread and worker objects are kept as attributes** so they stay in scope.
- **No schema change in the app's SQLite.** Hub readings are never written to `pp_control_history`.
- **Cross-thread signals connect to bound methods,** not lambdas.
- **Times:** UTC in data and code, local time only in UI text.
- **Hub:** `ids` is capped at 100, `since` is clamped to at most 14 days back, a bad `since` gives 400, and an unreachable database gives 503.
- **Tests:**
  - EDDataHub: `C:\Dev\EDDataHub\.venv\Scripts\python -m pytest`.
  - EDChronicle: `.venv\Scripts\python -m pytest`.
  - Qt tests need `QT_QPA_PLATFORM=offscreen`.
- **Commits:** no commit or push until Evan approves the finished result. Each task's "Commit" step means "stage only"; Evan's go-ahead triggers the actual commit.

## Review Focus

1. **Hub reachable but with no rows for a system.** The client returns `{}` for that system, not None, and the UI shows local data with no error. Test in Task 2.
2. **A reading timestamped before the reset in the merged list** (hub `since` edge, or a local row). It is ignored by `daily()` and `last_24h()`. Test in Task 3.
3. **Readings where U is None but R is set**, which `record_pp_control` allows. The day's `u` is None, not 0, and there's no crash. Test in Task 3.
4. **The selected watch row disappears after a refresh** because of the "Show only attacked" filter. The day table hides and nothing crashes. Test in Task 4.
5. **The hub answer arrives after the player has jumped on.** The chart ignores answers for a system that is no longer current. Test in Task 5.

---

### Task 1: Hub route `/api/system-powerplay`

**Files (repo `C:\Dev\EDDataHub`):**
- Modify: `eddatahub/bgs.py` (add a query and a function after `system_factions`)
- Modify: `eddatahub/web.py` (add a route after the `/api/system-factions` block, about line 569)
- Test: `tests/test_web.py`, `tests/test_bgs.py`

**Interfaces:**
- Produces: `GET /api/system-powerplay?ids=<int,...>&since=<ISO with zone>` returns a JSON list, oldest first, of `{"system": int, "time": ISO str, "state": str|None, "reinforcement": int|None, "undermining": int|None, "control": float|None}`.
- Produces: `bgs.system_powerplay(conn, ids: list[int], since: datetime) -> list[dict]`, in the same shape.

- [ ] **Step 1: Write the failing route test** in `tests/test_web.py`, modelled on `test_markets_streams_the_archive_gzipped`. It needs no database.

```python
def test_system_powerplay_checks_its_input():
    srv = web.make_server(web.Deck("postgresql://unused", web.Hub(), get=offline), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        assert call(port, "GET", "/api/system-powerplay?ids=1&since=yesterday")[0] == 400
        assert call(port, "GET", "/api/system-powerplay?ids=x&since=2026-10-22T07:00:00Z")[0] == 400
        assert call(port, "GET", "/api/system-powerplay?ids=1&since=2026-10-22T07:00:00Z")[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()
```

- [ ] **Step 2: Write the failing DB test** in `tests/test_bgs.py`, following that file's DB-fixture pattern; it is skipped without a database. Insert two `powerplay` observations for system 77 with `value` `{"PowerplayState": "Exploited", "PowerplayStateReinforcement": 100, "PowerplayStateUndermining": 50, "PowerplayStateControlProgress": 0.4}` at `since + 1 h` and `since + 2 h`, and one at `since − 1 h`. Assert `system_powerplay(conn, [77], since)` returns exactly the two later rows, oldest first, with `reinforcement == 100`, `undermining == 50`, `control == 0.4` and `state == "Exploited"`.

- [ ] **Step 3: Run both and verify they fail**

Run: `C:\Dev\EDDataHub\.venv\Scripts\python -m pytest tests/test_web.py::test_system_powerplay_checks_its_input tests/test_bgs.py -k system_powerplay -v`
Expected: FAIL. The route test gets 404 where 400/503 is expected; the DB test is skipped locally.

- [ ] **Step 4: Implement**
  - **`bgs.system_powerplay`:**
    - query: `SELECT system_id64, event_time, value FROM observation_history WHERE fact_type = 'powerplay' AND system_id64 = ANY(%s) AND event_time >= %s ORDER BY event_time`;
    - map the `value` keys `PowerplayState`, `PowerplayStateReinforcement`, `PowerplayStateUndermining` and `PowerplayStateControlProgress`;
    - give `time` as `event_time.isoformat()`.
  - **The route:**
    - parse `ids` as in `/api/system-factions` (`[:100]`, 400 on ValueError);
    - parse `since` as in `/api/markets` (400 without a zone);
    - clamp `since` to `max(since, now - timedelta(days=14))`;
    - on `psycopg.OperationalError`, return 503 `"database unreachable"`;
    - otherwise `self._send(200, dumps(rows))`.

- [ ] **Step 5: Run the hub suite**

Run: `C:\Dev\EDDataHub\.venv\Scripts\python -m pytest -q`
Expected: all pass (DB tests skipped locally).

- [ ] **Step 6: Stage**

```bash
git -C C:/Dev/EDDataHub add eddatahub/bgs.py eddatahub/web.py tests/test_web.py tests/test_bgs.py
```

### Task 2: App client `fetch_system_powerplay`

**Files:**
- Modify: `edc/core/eddatahub_client.py` (after `fetch_system_factions`)
- Test: `tests/test_eddatahub_pp_week.py` (new; HTTP server pattern from `tests/test_eddatahub_markets.py`)

**Interfaces:**
- Consumes: the Task 1 route.
- Produces: `fetch_system_powerplay(base_url: str, addresses: List[int], since: str) -> Optional[dict]` returns `{id64: [reading, ...]}`, where a reading is `{"observed_at": "YYYY-MM-DDTHH:MM:SSZ", "pp_state", "reinforcement", "undermining", "control", "source": "hub"}`, oldest first.
  - **Every requested id is a key,** with `[]` when the hub has no rows for it.
  - **Returns None** when `base_url` is empty, the address list is empty, the hub is unreachable, or the answer isn't a list.

- [ ] **Step 1: Write the failing tests.** Run a local HTTP server that answers `/api/system-powerplay` with `[{"system": 77, "time": "2026-10-23T10:00:00+00:00", "state": "Exploited", "reinforcement": 10, "undermining": 5, "control": 0.3}]`.

```python
def test_readings_come_back_per_system_in_app_shape(hub):
    got = fetch_system_powerplay(hub, [77, 88], "2026-10-22T07:00:00Z")
    assert got[77] == [{"observed_at": "2026-10-23T10:00:00Z", "pp_state": "Exploited", "reinforcement": 10,
                        "undermining": 5, "control": 0.3, "source": "hub"}]
    assert got[88] == []                     # asked for, hub has nothing: empty, not missing

def test_no_hub_means_none():
    assert fetch_system_powerplay("", [77], "2026-10-22T07:00:00Z") is None
    assert fetch_system_powerplay("http://127.0.0.1:9", [77], "2026-10-22T07:00:00Z") is None
```

- [ ] **Step 2: Run and verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_eddatahub_pp_week.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement** in the same style as `fetch_system_factions`:
  - chunks of 100;
  - `timeout=_TIMEOUT` and `USER_AGENT`;
  - times converted with `_z`;
  - `log.info` on failure.

- [ ] **Step 4: Run and verify they pass** with the same command.

- [ ] **Step 5: Stage**

```bash
git add edc/core/eddatahub_client.py tests/test_eddatahub_pp_week.py
```

### Task 3: Core `edc/core/pp_week.py`

**Files:**
- Create: `edc/core/pp_week.py`
- Modify: `persistence/repository.py` (add one reader after `get_pp_control_first`, about line 3352)
- Test: `tests/test_pp_week.py` (new)

**Interfaces:**
- Consumes: reading dicts with the keys `observed_at`, `pp_state`, `reinforcement`, `undermining`, `control` and `source`. These are both `pp_control_history` rows as dicts and Task 2 readings.
- Produces:
  - `Repository.get_pp_control_since(system_address: int, since: str) -> list[dict]`: rows with `observed_at >= since`, oldest first, as plain dicts.
  - `merge(local: list[dict], hub: list[dict]) -> list[dict]`: sorted by `observed_at`. Readings with equal `(observed_at, reinforcement, undermining)` appear once, and the local one is kept.
  - `daily(readings: list[dict], week_start: str, now: datetime) -> list[dict]`: one dict per UTC date from `week_start`'s date to `now`'s date, oldest first. Each dict is `{"day": date, "u": int|None, "r": int|None, "control": float|None, "state": str|None, "spans": int}`.
  - `last_24h(readings: list[dict], week_start: str, now: datetime) -> Optional[tuple[int, str]]`: `(gained, "up"|"down"|"flat")`.

**Rules for `daily`:**
- Readings before `week_start` are ignored.
- A day's `u` is its last reading's U minus the base. The base is the U of the most recent earlier day that has a reading, or 0 when there is none, since U and R reset at the tick. `r` works the same way.
- `spans` is the number of days back to that base day. It is 1 normally, or more after gap days. A day measured from the reset (base 0) has `spans` 1.
- A day with no reading has `u`, `r`, `control` and `state` all None.
- A reading whose U is None leaves `u` None for that day, and doesn't change the base for later days.

**Rules for `last_24h`:**
- Uses readings in `[week_start, now]` that have U set.
- `latest` is the newest of them. `base` is the newest one with `observed_at <= now − 24 h`.
- Returns None when `base` is missing, or `latest.observed_at <= now − 24 h`.
- Otherwise `gained = latest.u − base.u`, with direction "up" if > 0, "down" if < 0, else "flat".

- [ ] **Step 1: Write the failing tests**

```python
WS = "2026-10-22T07:00:00Z"          # Thursday reset
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)

def rd(t, u, r=0, src="eddn"):
    return {"observed_at": t, "pp_state": "Exploited", "reinforcement": r, "undermining": u,
            "control": 0.3, "source": src}

def test_merge_dedupes_keeping_local():
    a = rd("2026-10-23T10:00:00Z", 5, src="journal")
    assert merge([a], [rd("2026-10-23T10:00:00Z", 5, src="hub"), rd("2026-10-24T10:00:00Z", 9, src="hub")]) \
        == [a, rd("2026-10-24T10:00:00Z", 9, src="hub")]

def test_daily_reset_day_from_zero_gap_day_none_and_span():
    days = daily([rd("2026-10-21T23:00:00Z", 999),                 # before the reset: ignored
                  rd("2026-10-22T09:00:00Z", 100, 10),
                  rd("2026-10-22T20:00:00Z", 120, 15),
                  rd("2026-10-25T08:00:00Z", 300, 40)], WS, NOW)
    assert [d["day"].isoformat() for d in days] == ["2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"]
    assert (days[0]["u"], days[0]["r"], days[0]["spans"]) == (120, 15, 1)
    assert days[1]["u"] is None and days[1]["state"] is None
    assert (days[3]["u"], days[3]["r"], days[3]["spans"]) == (180, 25, 3)
    assert days[4]["u"] is None

def test_daily_none_undermining_stays_none():
    r = rd("2026-10-23T10:00:00Z", None, 50)
    days = daily([rd("2026-10-22T10:00:00Z", 10), r, rd("2026-10-24T10:00:00Z", 30)], WS, NOW)
    assert days[1]["u"] is None and days[1]["r"] == 50
    assert days[2]["u"] == 20 and days[2]["spans"] == 2

def test_last_24h():
    rs = [rd("2026-10-25T08:00:00Z", 300), rd("2026-10-26T10:00:00Z", 420)]
    assert last_24h(rs, WS, NOW) == (120, "up")
    assert last_24h(rs[1:], WS, NOW) is None                         # nothing 24 h old
    assert last_24h(rs[:1], WS, NOW) is None                         # nothing in the last 24 h
```

A test for `get_pp_control_since`, using the `_repo` helper pattern from `tests/test_pp_control_history.py`: two `record_pp_control` rows, one before `since` and one after. Only the later one comes back, as a dict.

- [ ] **Step 2: Run and verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_pp_week.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the four functions** following the rules above. They are pure, and parse ISO times with `datetime.fromisoformat(s.replace("Z", "+00:00"))`.

- [ ] **Step 4: Run and verify they pass** with the same command.

- [ ] **Step 5: Stage**

```bash
git add edc/core/pp_week.py persistence/repository.py tests/test_pp_week.py
```

### Task 4: Hub worker, plus the Watch List column and day table

**Files:**
- Create: `edc/ui/pp_week_worker.py`
- Modify: `edc/ui/panels/powerplay_watch_panel.py`
- Test: `tests/test_pp_week_watch.py` (new, Qt offscreen)

**Interfaces:**
- Consumes: `fetch_system_powerplay` (Task 2); `merge`, `daily`, `last_24h` and `Repository.get_pp_control_since` (Task 3); `bgs_tasks.powerplay_week_start`; `self._panel.eddatahub_url` (already set by `MainWindow` on the player faction panel).
- Produces: the `HubPowerplayFetch` class in `pp_week_worker.py`.
  - `HubPowerplayFetch.start(hub_url: str, ids: list[int], since: str) -> None` starts a background fetch unless all ids are cached younger than 600 s, in which case it emits `done` at once with the cached data.
  - `HubPowerplayFetch.done = pyqtSignal(dict)` emits `{id64: [readings]}` for the ids asked, and `{}` on failure or with no hub.
  - It owns its QThread and worker as attributes. A new `start()` while one is running is ignored.
  - The cache is module-level: `{id64: (fetched_monotonic, readings)}`.
- **Watch panel additions:**
  - column `"U 24 h"`, inserted before `"Data"`;
  - `self._day_table: QTableWidget`, columns `["Day", "U", "R", "Progress", "State"]`, hidden when no row is selected;
  - `self._hub: dict` holding the latest hub readings;
  - `self._fetch: HubPowerplayFetch`, whose `done` is connected to the bound method `self._on_hub`.

- [ ] **Step 1: Write the failing tests**

```python
def test_watch_shows_24h_column_and_day_table(qapp, panel_with_rows):   # fixture: 1 watched row "Ys", 2 local readings
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh()
    hdr = [w._table.horizontalHeaderItem(c).text() for c in range(w._table.columnCount())]
    assert "U 24 h" in hdr
    assert w._day_table.isHidden()
    w._table.selectRow(0)
    assert not w._day_table.isHidden() and w._day_table.rowCount() >= 1

def test_day_table_hides_when_selected_row_filtered_away(qapp, panel_with_rows):
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh(); w._table.selectRow(0)
    w._only_attacked.setChecked(True)          # Ys is "holding": filtered out
    assert w._day_table.isHidden()

def test_hub_readings_merge_in(qapp, panel_with_rows):
    w = PowerPlayWatchPanel(panel_with_rows)
    w._only_attacked.setChecked(False); w.refresh()
    w._on_hub({77: [hub_reading_24h_ago_with_lower_u]})
    assert "↑" in w._table.item(0, w._col("U 24 h")).text()
```

Build `panel_with_rows` from the existing `tests/test_pp_control_history.py` `_repo` pattern. Use a `SimpleNamespace` panel with `_repo`, `eddatahub_url=""`, `pledged_power_getter`, `edsm_powerplay=None` and `_latest_known_tick=None`, and monkeypatch `pp_watch` so it returns `{77: "squad system"}`.

- [ ] **Step 2: Run and verify they fail**

Run: `set QT_QPA_PLATFORM=offscreen&& .venv\Scripts\python -m pytest tests/test_pp_week_watch.py -v`
Expected: FAIL (no "U 24 h" column).

- [ ] **Step 3: Implement**
  - **`HubPowerplayFetch`:** follow the pattern of `_HubMarketCatchUpWorker` in `edc/ui/main_window.py`, where the worker's `finished` triggers `thread.quit` with a DirectConnection. Fetching doesn't touch SQLite, so no Database is needed.
  - **`refresh()`:** after `watch_rows`, read local readings per row with `get_pp_control_since(addr, powerplay_week_start())` into `self._local`, then call `self._fetch.start(self._panel.eddatahub_url, ids, week_start)`.
  - **`_fill()`:**
    - `last_24h(merge(local, hub), ...)` gives "+N ↑", "−N ↓" or "0 ↔", or "—" for None;
    - `_NumItem` sorts by `gained`;
    - the cell is red (`_RED`) when "up".
  - **`_on_hub(data)`:** updates `self._hub`, refills the table, and refreshes the day table.
  - **`itemSelectionChanged`:** also fills `_day_table` from `daily(merge(...), week_start, now)`.
    - Each cell shows "—" for None.
    - U and R get a "*" suffix when `spans > 1`, with the tooltip "change since <day − spans>".
    - The reset day's U cell gets the tooltip "includes the weekly decay set at the reset".
    - Progress shows as `f"{control*100:.1f}%"`.
  - **The row click** still copies the name (`cellClicked`, unchanged).

- [ ] **Step 4: Run and verify the tests pass,** then run the full suite with `.venv\Scripts\python -m pytest -q`.

- [ ] **Step 5: Stage**

```bash
git add edc/ui/pp_week_worker.py edc/ui/panels/powerplay_watch_panel.py tests/test_pp_week_watch.py
```

### Task 5: Status tab chart

**Files:**
- Create: `edc/ui/pp_week_chart.py`
- Modify: `edc/ui/panels/powerplay_panel.py`:
  - store `self._repo = repo` in `__init__`;
  - add `self.eddatahub_url = ""`;
  - add the chart under `pp_conflict_banner`.
- Modify: `edc/ui/main_window.py`, after `self.powerplay_panel = PowerplayPanel(...)` (about line 2966): set `self.powerplay_panel.eddatahub_url = getattr(self.cfg, "eddatahub_url", "") or ""`.
- Test: `tests/test_pp_week_chart.py` (new, Qt offscreen)

**Interfaces:**
- Consumes: Task 3 functions and `HubPowerplayFetch` (Task 4).
- Produces: `PPWeekChart(QWidget)`.
  - `set_data(readings: list[dict], week_start: str, now: datetime) -> None` stores the readings and calls `update()`.
  - `paintEvent` draws U (`#FF6B6B`) and R (`#4D96FF`) as step lines over `[week_start, now]`, with day names on the x-axis and the latest values at the right.
  - `sizeHint()` is about `QSize(400, 90)`.
  - `caption() -> str` returns "N reports this week · last <age> ago", or "" when there's no data.

- [ ] **Step 1: Write the failing tests**

```python
def test_chart_hidden_without_readings_and_shown_with(qapp, pp_panel):   # PowerplayPanel(repo=tmp repo)
    state = SimpleNamespace(system_address=77, system="Ys", pp_power="Aisling Duval",
                            system_controlling_power="Aisling Duval", system_powerplay_state="Exploited",
                            system_powers=[], system_powerplay_conflict_progress={},
                            system_powerplay_reinforcement=10, system_powerplay_undermining=5,
                            system_powerplay_control_progress=0.3)
    pp_panel.refresh(state)
    assert pp_panel.pp_week_chart.isHidden()
    record_two_readings(pp_panel._repo, 77)
    pp_panel.refresh(state)
    assert not pp_panel.pp_week_chart.isHidden()
    assert pp_panel.pp_week_chart.grab().width() > 0          # paints without error

def test_late_hub_answer_for_old_system_is_ignored(qapp, pp_panel):
    ...refresh into system 77, then system 88...
    pp_panel._on_pp_hub({77: [reading]})
    assert pp_panel._pp_week_for == 88 and pp_panel.pp_week_chart._readings == local_readings_for_88
```

- [ ] **Step 2: Run and verify they fail**

Run: `set QT_QPA_PLATFORM=offscreen&& .venv\Scripts\python -m pytest tests/test_pp_week_chart.py -v`
Expected: FAIL (`pp_week_chart` missing).

- [ ] **Step 3: Implement**
  - **In `PowerplayPanel.refresh`:**
    - when `state.system_address` differs from `self._pp_week_for`, set it, read the local readings (`get_pp_control_since`), call `set_data`, and call `self._pp_fetch.start(self.eddatahub_url, [addr], week_start)`;
    - show the chart only when the system has a controlling power and at least one reading;
    - skip silently when `self._repo` is None.
  - **`_on_pp_hub(data)` is a bound slot:** it ignores data that doesn't contain `self._pp_week_for`, otherwise merges and calls `set_data`.
  - **Caption:** a QLabel under the chart showing `chart.caption()`.

- [ ] **Step 4: Run and verify the tests pass, then run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Run the app** with `.venv\Scripts\python main.py` (the project's normal start). Confirm:
  - the PowerPlay window opens;
  - the Watch List shows "U 24 h";
  - selecting a row shows the day table;
  - the Status tab shows the chart in a system with readings;
  - the log has no new exceptions.

- [ ] **Step 6: Stage**

```bash
git add edc/ui/pp_week_chart.py edc/ui/panels/powerplay_panel.py edc/ui/main_window.py tests/test_pp_week_chart.py
```

### Task 6: Deploy and confirm

- [ ] **Step 1:** Evan approves. Commit and push both repos. In EDDataHub, commit "feat: /api/system-powerplay for EDChronicle's PowerPlay week history"; in EDChronicle, "feat: PowerPlay week history: status chart, watch list U 24 h and day table".
- [ ] **Step 2:** Evan runs `sudo bash /opt/eddatahub/app/deploy/update.sh` on the server.
- [ ] **Step 3:** Check the live route: `curl -s "http://172.16.10.197:8080/api/system-powerplay?ids=<Ys id64>&since=<week start>"` returns rows.
- [ ] **Step 4:** Evan confirms in the app: arriving in Ys shows a chart, and the watch list day table fills in after the hub answers.
