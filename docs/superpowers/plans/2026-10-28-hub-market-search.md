# Hub-first Market Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EDDataHub stores the latest market of every station and answers radius searches; EDChronicle's two market searches ask the hub first and fall back to the local table.

**Architecture:** Hub: new `eddatahub/markets.py` (pure snapshot parsing + SQL write/search/prune/backfill), fed by the existing listener's writer thread, one new migration, one new route `/api/market-search`. Positions are resolved once at write time (system name → x/y/z) and stored on the row, so a search is a single indexed table read. App: `fetch_market_search` in the hub client (3 s timeout, 60 s skip after a failure); `Repository.search_market_prices` / `search_market_prices_multi` try it first.

**Tech Stack:** Hub: Python 3, psycopg 3, Postgres, stdlib `http.server`. App: Python 3, `requests`, SQLite, PyQt6 (unchanged).

**Spec:** `docs/superpowers/specs/2026-10-28-hub-market-search-design.md` (EDChronicle repo).

**Repos:** Tasks 1–3 in `C:\Dev\EDDataHub`. Tasks 4–5 in `C:\Dev\EDChronicle`. Separate branches, one per repo.

## Global Constraints

- Hub keeps only the latest price per station × commodity: no history.
- Hub market rows pruned at 21 days; app local prune unchanged at 21 days.
- Local ingestion, local schema, local prune, trade-route lookup (`trade_route_panel.py:197`), `search_fleet_carrier_materials`: unchanged.
- No UI change; results carry no source label.
- Commodity names stored as EDDN sends them (`name`, e.g. `platinum`), matching the app's `net.market_prices.commodity_name`.
- Drop messages more than 10 minutes in the future (`parse.MAX_FUTURE`).
- `last_updated` returned as `YYYY-MM-DDTHH:MM:SSZ`.
- Fleet carrier filter: market `station_type = 'FleetCarrier'`, or hub `station` fact `StationType = 'FleetCarrier'`, or station name matches `^[A-Z0-9]{3}-[A-Z0-9]{3}$`.
- `/api/market-search` answers 503 until the backfill has completed once.
- App search timeout 3 s; after a hub failure, skip the hub for 60 s.
- Hub DB tests need `TEST_DATABASE_URL` and skip without it (existing pattern in `tests/test_db.py`). Pure functions must be tested without a DB.
- No commits to `main` directly; no push without Evan's go-ahead.

## Review Focus

1. A station's newer snapshot lists fewer commodities → dropped commodities disappear for that station (Task 1 test `test_write_replaces_whole_station`).
2. An older snapshot arriving after a newer one (archive backfill overlapping live feed) → ignored (Task 1 test `test_write_ignores_older_snapshot`).
3. Hub reachable but table not backfilled → app uses local (Task 3 test `test_market_search_503_until_ready`, Task 4 test `test_fetch_market_search_non_200_is_none`).
4. Hub down → second search inside 60 s does not wait for the hub (Task 4 test `test_fetch_market_search_skips_hub_after_failure`).
5. Hub row with null pads where the local `station_info` knows the pads → sorted as known pad (Task 5 test `test_hub_rows_fill_pads_from_local_station_info`).

---

### Task 1: Hub market table, snapshot parsing and writes

**Files:**
- Create: `C:\Dev\EDDataHub\sql\015_market_prices.sql`
- Create: `C:\Dev\EDDataHub\eddatahub\markets.py`
- Modify: `C:\Dev\EDDataHub\eddatahub\parse.py` (comment at line 8 only: markets are now stored in `market_prices`, not as facts)
- Test: `C:\Dev\EDDataHub\tests\test_markets.py`

**Interfaces:**
- Produces:
  - `markets.Snapshot` — NamedTuple `(market_id: int, station_name: str, station_type: str, system_name: str, updated_at: datetime, rows: list[tuple])`; each row `(commodity, sell_price, buy_price, mean_price, demand, demand_bracket, stock, stock_bracket)`.
  - `markets.snapshot(envelope: dict) -> Snapshot | None` — pure.
  - `markets.write(conn, snaps: list[Snapshot]) -> int` — rows written.
  - `markets.prune(conn, now: datetime) -> int` — rows deleted.

Migration `015_market_prices.sql`:

```sql
-- Latest market of every station (commodity/3), for /api/market-search. No history; pruned at 21 days.
CREATE TABLE market_prices (
  market_id      bigint      NOT NULL,
  commodity      text        NOT NULL,
  station_name   text        NOT NULL,
  station_type   text        NOT NULL,
  system_name    text        NOT NULL,
  x double precision, y double precision, z double precision,   -- from the system's position at write time; null if unknown
  sell_price integer, buy_price integer, mean_price integer,
  demand integer, demand_bracket integer, stock integer, stock_bracket integer,
  updated_at     timestamptz NOT NULL,
  PRIMARY KEY (market_id, commodity)
);
CREATE INDEX ON market_prices (commodity, x, z);
CREATE INDEX ON market_prices (updated_at);
CREATE INDEX ON current_facts (lower(value ->> 'StarSystem')) WHERE fact_type = 'system';
CREATE INDEX ON region_systems (lower(name));
CREATE TABLE market_state (id integer PRIMARY KEY CHECK (id = 1), backfilled_at timestamptz);
```

- [ ] **Step 1: Write the failing tests** in `tests/test_markets.py`

Pure (no DB):
```python
def env(ts="2026-10-28T10:00:00Z", market_id=128, commodities=None, **kw):
    return {"$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {"gatewayTimestamp": "2026-10-28T10:00:01Z"},
            "message": {"marketId": market_id, "systemName": "Ekono", "stationName": "Ross Port",
                        "stationType": "Coriolis", "timestamp": ts,
                        "commodities": commodities if commodities is not None else
                        [{"name": "gold", "sellPrice": 9000, "buyPrice": 0, "meanPrice": 9500, "demand": 100,
                          "demandBracket": 2, "stock": 0, "stockBracket": 0}], **kw}}

def test_snapshot_reads_commodity_message():
    s = markets.snapshot(env())
    assert (s.market_id, s.system_name, s.station_name, s.station_type) == (128, "Ekono", "Ross Port", "Coriolis")
    assert s.rows == [("gold", 9000, 0, 9500, 100, 2, 0, 0)]

def test_snapshot_rejects_bad_input():
    assert markets.snapshot({"$schemaRef": "https://eddn.edcd.io/schemas/journal/1", "message": {}}) is None
    assert markets.snapshot(env(market_id="x")) is None
    assert markets.snapshot(env(ts="2099-01-01T00:00:00Z")) is None          # > 10 min after gatewayTimestamp
    assert markets.snapshot(env(commodities=[{"name": ""}, "junk", {"name": "gold", "sellPrice": "lots"}])).rows \
        == [("gold", None, None, None, None, None, None, None)]             # non-int numbers become None
```

DB-backed (use the `conn` fixture pattern from `tests/test_db.py`, skip without `TEST_DATABASE_URL`):
- `test_write_stores_position_from_system_fact` — seed a `current_facts` `system` row `{"StarSystem": "Ekono", "StarPos": [1.0, 2.0, 3.0]}`; write `snapshot(env())`; row has x, y, z = 1, 2, 3.
- `test_write_uses_region_systems_when_no_fact` — only `region_systems` has `Ekono`; position comes from it. Neither has it → x/y/z null.
- `test_write_replaces_whole_station` — write gold+silver at 10:00, then gold only at 11:00 → only gold remains for market 128.
- `test_write_ignores_older_snapshot` — write 11:00 then 10:00 → 11:00 values remain.
- `test_prune_drops_rows_older_than_21_days`.

- [ ] **Step 2: Run** `pytest tests/test_markets.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `markets.py`**

`snapshot`: schema must equal `parse.COMMODITY`; `marketId` int; `systemName`/`stationName` non-empty str; `stationType` str or `""`; `timestamp` parsed with `parse._ts`, dropped if more than `parse.MAX_FUTURE` after `header.gatewayTimestamp`; commodities: dicts with non-empty str `name`, numeric fields kept only if `type(v) is int`, else None.

`write`, per snapshot in one transaction: skip if the station already has a row with `updated_at >= snap.updated_at`; resolve position (`current_facts` system fact by `lower(value->>'StarSystem')`, StarPos 3 finite numbers; else `region_systems` by `lower(name)`); `DELETE FROM market_prices WHERE market_id = %s`; insert all rows (`executemany`). Cache name → position within one call.

`prune`: `DELETE FROM market_prices WHERE updated_at < now - 21 days`. `KEEP = timedelta(days=21)`.

- [ ] **Step 4: Run** `pytest tests/test_markets.py -v` (and with `TEST_DATABASE_URL` set if a test DB is available) — Expected: pure tests PASS; DB tests PASS or SKIP. Run full `pytest` — no regressions.

- [ ] **Step 5: Commit** `feat: market_prices table and commodity/3 snapshot writes`

---

### Task 2: Feed the table — live listener, backfill command, maintain prune

**Files:**
- Modify: `C:\Dev\EDDataHub\eddatahub\eddn.py` (`listen`, `_writer`)
- Modify: `C:\Dev\EDDataHub\eddatahub\markets.py` (add `backfill`)
- Modify: `C:\Dev\EDDataHub\eddatahub\maintain.py` (`run`)
- Modify: `C:\Dev\EDDataHub\eddatahub\__main__.py` (new `market-backfill` command, docstring)
- Test: `tests/test_markets.py`, `tests/test_eddn.py`, `tests/test_maintain.py`

**Interfaces:**
- Consumes: `markets.snapshot`, `markets.write`, `markets.prune` (Task 1).
- Produces: `markets.backfill(conn, root: Path, now: datetime) -> dict` returning `{"stations": int, "rows": int, "no_position": int}`; sets `market_state.backfilled_at = now()`.

- [ ] **Step 1: Write the failing tests**
- `test_backfill_writes_newest_snapshot_and_marks_ready` (DB): archive dir with two hours of gz files (use the archive-writing helpers already in `tests/test_eddn.py`), same station in both; after `backfill`, rows hold the newer snapshot, `market_state.backfilled_at` is set, returned `stations == 1`.
- `test_backfill_counts_stations_without_position` (DB): system unknown → `no_position == 1`.
- In `tests/test_eddn.py`: a commodity/3 envelope fed through the listener path reaches `markets.write` (monkeypatch `markets.write` to record calls, same style as existing listener tests).
- In `tests/test_maintain.py` (DB): `maintain.run` deletes a 22-day-old `market_prices` row and its returned counts include `"markets_deleted": 1`.

- [ ] **Step 2: Run** the new tests — Expected: FAIL.

- [ ] **Step 3: Implement**
- `listen`: for an envelope with `$schemaRef == COMMODITY`, append `markets.snapshot(env)` (when not None) to a `snaps` list next to `batch`; flush it in the same queue item: `q.put_nowait((batch, snaps, now))`, flushing when either is non-empty. Overflow/drop logging counts both.
- `_writer`: unpack `(batch, snaps, now)`; after `db.write_batch`, `markets.write(conn, snaps)` inside the same retry loop; stats key `"markets"` += rows written.
- `backfill`: walk `eddn.latest_markets(root, now - markets.KEEP, now)` (newest first, one message per station already), convert each message to a `Snapshot` (wrap as an envelope or factor a `_from_message` used by `snapshot`), write in chunks of 500, log progress every 5,000 stations, log the final dict, then set `market_state` (`INSERT ... ON CONFLICT (id) DO UPDATE`).
- `maintain.run`: call `markets.prune(conn, now)`, add `"markets_deleted"` to the counts.
- `__main__`: `market-backfill` → `markets.backfill(conn, state_dir() / "eddn", datetime.now(timezone.utc))`, print the dict.

- [ ] **Step 4: Run** full `pytest` — Expected: PASS (DB tests PASS or SKIP).

- [ ] **Step 5: Commit** `feat: feed market_prices from the listener, backfill command, 21-day prune`

---

### Task 3: `/api/market-search`

**Files:**
- Modify: `C:\Dev\EDDataHub\eddatahub\markets.py` (add `search`, `ready`)
- Modify: `C:\Dev\EDDataHub\eddatahub\web.py` (route in `do_GET`, next to `/api/system-powerplay`)
- Test: `tests/test_markets.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: Task 1 table.
- Produces:
  - `markets.ready(conn) -> bool` — `market_state.backfilled_at` is set.
  - `markets.search(conn, commodities: list[str], x: float, y: float, z: float, radius: float, exclude: int | None) -> list[dict]`
  - `GET /api/market-search?commodity=gold,silver&x=&y=&z=&radius=&exclude=` → 200 JSON list of dicts with keys `market_id, commodity, station_name, station_type, system_name, sell_price, demand, stock, last_updated, x, y, z, distance_ly, pads_small, pads_medium, pads_large, station_faction`; 400 bad input; 503 not ready or DB unreachable.

- [ ] **Step 1: Write the failing tests**
- `tests/test_web.py`, following `test_system_powerplay_checks_its_input`:
  - `test_market_search_checks_its_input` — 400 for missing commodity, non-numeric or non-finite x/y/z/radius, radius ≤ 0 or > 1000, more than 200 commodities, non-int exclude; valid input with no DB → 503.
- `tests/test_markets.py` (DB):
  - `test_market_search_503_until_ready` — through the web handler or `markets.ready`: false before backfill, true after.
  - `test_search_filters_like_local` — rows for: in radius (kept); in box but outside sphere (dropped); `sell_price` null (dropped); `station_type` `FleetCarrier` (dropped); name `K7Q-1HT` (dropped); market row type `""` but station fact `StationType` `FleetCarrier` (dropped); 22 days old (dropped); `market_id == exclude` (dropped); x null (dropped).
  - `test_search_adds_station_facts` — station fact `{"LandingPads": {"Small": 4, "Medium": 4, "Large": 2}, "StationFaction": {"Name": "Ekono Ltd"}}` keyed by market id → `pads_large == 2`, `station_faction == "Ekono Ltd"`; no fact → pads and faction null.
  - `test_search_last_updated_format` — `last_updated == "2026-10-28T10:00:00Z"`, `distance_ly` correct to 1e-6.

- [ ] **Step 2: Run** — Expected: FAIL.

- [ ] **Step 3: Implement**
- `search`: one query: `market_prices` `WHERE commodity = ANY(%s) AND sell_price IS NOT NULL AND updated_at >= now() - KEEP AND x BETWEEN … AND y BETWEEN … AND z BETWEEN … AND station_type <> 'FleetCarrier' AND station_name !~ '^[A-Z0-9]{3}-[A-Z0-9]{3}$'`, `LEFT JOIN current_facts f ON f.fact_type = 'station' AND f.entity_key = market_id::text`, exclude `f.value->>'StationType' = 'FleetCarrier'`; Python computes true distance, drops > radius, builds dicts. `LandingPads` values kept only if int; `StationFaction` name kept only if str.
- Route: parse `commodity` (comma-split, stripped, non-empty, ≤ 200), floats via `float()` + `math.isfinite`, `0 < radius <= 1000`, optional int `exclude`; `with db.connect(dk.url) as conn:` → `if not markets.ready(conn): return self._error(503, "market table not ready")`; `psycopg.OperationalError` → 503 `"database unreachable"`.

- [ ] **Step 4: Run** full `pytest` — Expected: PASS (DB tests PASS or SKIP).

- [ ] **Step 5: Commit** `feat: /api/market-search over market_prices`

- [ ] **Step 6: Server check (Evan runs, after merge + deploy)**

```bash
sudo bash /opt/eddatahub/app/deploy/update.sh
sudo -u eddatahub bash -c 'set -a; . /etc/eddatahub.env; set +a; cd /opt/eddatahub/app && STATE_DIRECTORY=/var/lib/eddatahub .venv/bin/python -m eddatahub market-backfill'
curl -s 'http://172.16.10.197:8080/api/market-search?commodity=gold&x=0&y=0&z=0&radius=50' | head -c 600
```
Expected: backfill prints `{"stations": N, "rows": M, "no_position": K}` with K small relative to N; curl returns a JSON list (503 before the backfill finishes). The web role reads the new tables through the default privileges in `deploy/web-role.sql`; no grant change needed.

---

### Task 4: App client `fetch_market_search`

**Files:**
- Modify: `C:\Dev\EDChronicle\edc\core\eddatahub_client.py`
- Test: `C:\Dev\EDChronicle\tests\test_eddatahub_market_search.py`

**Interfaces:**
- Produces: `fetch_market_search(base_url: str, commodities: list[str], x: float, y: float, z: float, radius: float, exclude_market_id: Optional[int] = None) -> Optional[list[dict]]` — hub rows as returned (Task 3 keys), `None` on any failure or while skipping. Module constants `_SEARCH_TIMEOUT = 3`, `_SEARCH_SKIP_S = 60`.

- [ ] **Step 1: Write the failing tests** (local `HTTPServer` fixture as in `tests/test_eddatahub_pp_week.py`; reset the module's skip state between tests)
- `test_fetch_market_search_returns_rows` — server returns one row; result equals it; request path carries `commodity=gold,silver`, `x`, `y`, `z`, `radius`, and `exclude` only when given.
- `test_fetch_market_search_non_200_is_none` — server answers 503 → `None`.
- `test_fetch_market_search_bad_json_is_none` — body `not json` and body `{"a": 1}` (not a list) → `None`.
- `test_fetch_market_search_skips_hub_after_failure` — first call to a closed port → `None`; second call within 60 s to a live server → `None` without a request reaching it; after advancing `time.monotonic` (monkeypatch) past 60 s → rows.

- [ ] **Step 2: Run** `pytest tests/test_eddatahub_market_search.py -v` — Expected: FAIL (import error).

- [ ] **Step 3: Implement** with `requests.get(..., params=..., headers={"User-Agent": USER_AGENT}, timeout=_SEARCH_TIMEOUT)`, same style as `fetch_system_powerplay`; on failure set a module-level `_skip_until = time.monotonic() + _SEARCH_SKIP_S` and log one warning per skip window.

- [ ] **Step 4: Run** — Expected: PASS.

- [ ] **Step 5: Commit** `feat: EDDataHub market search client with 60 s skip after failure`

---

### Task 5: Repository asks the hub first

**Files:**
- Modify: `C:\Dev\EDChronicle\persistence\repository.py` (`search_market_prices` ~2271, `search_market_prices_multi` ~2339, class attribute on `Repository`)
- Modify: `C:\Dev\EDChronicle\edc\ui\main_window.py` (set the hub URL once at startup, where `eddatahub_url` is first read from `self.cfg`)
- Test: `C:\Dev\EDChronicle\tests\test_market_radius_queries.py`

**Interfaces:**
- Consumes: `fetch_market_search` (Task 4).
- Produces: `Repository.hub_url: str = ""` class attribute; `main_window` sets `Repository.hub_url = getattr(self.cfg, "eddatahub_url", "") or ""` once at startup, so worker-thread `Repository` instances see it.

- [ ] **Step 1: Write the failing tests** (monkeypatch `persistence.repository.fetch_market_search`; set/reset `Repository.hub_url` per test)
- `test_hub_rows_used_when_hub_answers` — hub returns a row for a station the local DB does not have → it is in `search_market_prices` results with `distance_ly`, `pad_size`, `pad_known` set; local-only rows absent.
- `test_hub_empty_list_is_an_answer` — hub returns `[]` while local has a match → result `[]`.
- `test_hub_none_falls_back_to_local` — hub returns `None` → today's local result.
- `test_no_hub_url_never_calls_hub` — `hub_url == ""` → fetch not called.
- `test_hub_rows_fill_pads_from_local_station_info` — hub row pads null, local `net.station_info` has `pads_large=2` for that `market_id` → `pad_known` True and sorted before an unknown-pad row with a higher price.
- `test_multi_groups_hub_rows_by_commodity` — `search_market_prices_multi(["gold", "silver"], …)` with hub rows for both → dict with both keys, each sorted known-pad first then `-sell_price`; a requested commodity with no rows → `[]`.

- [ ] **Step 2: Run** `pytest tests/test_market_radius_queries.py -v` — Expected: new tests FAIL.

- [ ] **Step 3: Implement**
- Import `fetch_market_search` at module level in `repository.py` (so tests can patch it).
- One private helper `_hub_market_rows(self, commodity_names, x, y, z, radius_ly, exclude_market_id) -> Optional[list[dict]]`: returns None when `not self.hub_url` or the fetch returns None; otherwise fills null pads (and null `station_faction`) from `net.station_info` by `market_id` (chunked `IN` lists of ≤ 900), then sets `pad_size` / `pad_known` with `effective_pad_size`, and maps `commodity` → `commodity_name`.
- `search_market_prices`: `rows = self._hub_market_rows([commodity_name], ...)`; if not None, sort `(not pad_known, -sell_price)` and return; else existing body unchanged.
- `search_market_prices_multi`: same, grouped into `{name: [] for name in commodity_names}`. Hub requests above 200 names: split into chunks of 200; any chunk returning None → whole call falls back to local.
- Do not touch the local query bodies.

- [ ] **Step 4: Run** full `pytest` — Expected: PASS (1582+ tests).

- [ ] **Step 5: Run the app** — `python main.py` (or the project's usual launch), open Market search and Mining sell search with the hub up; then with `eddatahub_url` pointing at an unused port: searches still return local results, and the second search does not pause 3 s.

- [ ] **Step 6: Commit** `feat: market searches ask EDDataHub first, local table as fallback`
