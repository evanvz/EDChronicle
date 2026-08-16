# Market Radius-Search SQL Variable Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `sqlite3.OperationalError: too many SQL variables` crash in Fleet Carrier material search (and the same latent bug in 4 sibling functions) by moving the radius bounding-box filter from a Python-built `IN (...)` list into a SQL `JOIN`, and close a related unbounded-growth gap in `fleet_carrier_materials`.

**Architecture:** `persistence/repository.py`'s `_nearby_system_coords()` helper and its 5 callers currently pre-fetch every system inside a bounding box into Python, then bind one SQL parameter per system name. This plan replaces that with an `INNER JOIN system_coords` directly in each query's `WHERE` clause, making bound-parameter count constant regardless of table size. A new worker-triggered index speeds the JOIN up without risking a startup freeze. `fleet_carrier_materials` gains the same age-based `DELETE` pruning `market_prices` already has.

**Tech Stack:** Python 3, SQLite3 (stdlib `sqlite3`), pytest.

## Global Constraints

- `search_fleet_carrier_materials`'s `INNER JOIN station_info si ON si.market_id = fcm.market_id` wording must not change — pinned by an existing test (`tests/test_fleet_carrier_materials.py::test_uses_inner_join_against_station_info_not_left_join`, which asserts `"INNER JOIN station_info" in source` and `"LEFT JOIN station_info" not in source` via `inspect.getsource`).
- No change to any of the 5 functions' sorting, `exclude_market_id` filtering, pad-size resolution, or per-row dict-building logic — this is a WHERE-clause/JOIN mechanism swap only, not a behavior change.
- `get_market_snapshot_for_systems` (`persistence/repository.py`, exact-name-list based) and `get_system_coords_for_names` (same file, same pattern) are explicitly OUT OF SCOPE — they're bounded by a caller-supplied exact list, not by unbounded table growth, and must not be touched.
- No database file splitting, no age-based pruning of `system_coords` itself — both explicitly rejected in the design spec (`docs/superpowers/specs/2026-08-15-market-radius-search-sql-limit-design.md`).
- The new `idx_system_coords_xyz` index must be created from a worker-triggered method (`ensure_system_coords_indexes()`, called from `_MarketVacuumWorker.run()`), NOT added to the auto-run `run_migrations()` flat list — `run_migrations()` runs synchronously on the main/UI thread every startup, and an index build on a large, continuously-growing table risks freezing app launch (same reasoning already applied to the existing `ensure_market_prices_indexes()`).

---

### Task 1: Rewrite the 5 radius-search functions to use a SQL JOIN instead of a Python-built IN-list

**Files:**
- Modify: `persistence/repository.py` (delete `_nearby_system_coords`; rewrite `search_market_prices`, `search_market_prices_multi`, `search_fleet_carrier_materials`, `search_market_buy_prices`, `get_market_snapshot_in_radius`)
- Modify: `persistence/database.py` (add `ensure_system_coords_indexes()`)
- Modify: `edc/ui/main_window.py` (call the new index method from `_MarketVacuumWorker.run()`)
- Test: `tests/test_fleet_carrier_materials.py` (add one regression test)
- Test: `tests/test_market_radius_queries.py` (new file, covers the other 4 functions)

**Interfaces:**
- Consumes: existing `Repository.save_system_coords_batch(records: list[tuple[str, float, float, float, str]])` (records: `(system_name, x, y, z, last_seen)`), existing `Repository.save_market_snapshot_batch(records: list[tuple])` (records: `(market_id, commodity_name, station_name, station_type, system_name, sell_price, buy_price, mean_price, demand, demand_bracket, stock, stock_bracket, last_updated)`), existing `Repository.save_fleet_carrier_materials_batch(records: list[tuple])` (records: `(market_id, material_symbol, carrier_name, carrier_id, price, stock, demand, last_updated)`), existing `Repository.save_station_info_batch(records: list[dict])`.
- Produces: `Repository.search_market_prices`, `search_market_prices_multi`, `search_fleet_carrier_materials`, `search_market_buy_prices`, `get_market_snapshot_in_radius` — same signatures and return shapes as before, internals only. `Database.ensure_system_coords_indexes(self) -> None`, consumed by Task 1's own `main_window.py` change (no other task depends on it).

- [ ] **Step 1: Re-read the current state of all 6 functions in `persistence/repository.py`**

Read `_nearby_system_coords` and its 5 callers in full before editing anything — this file is large and frequently touched; do not trust remembered line numbers. Confirm each function's exact current text matches the shapes described below before making any change.

- [ ] **Step 2: Delete `_nearby_system_coords`**

Delete this entire method:

```python
def _nearby_system_coords(self, x: float, y: float, z: float, radius_ly: float) -> dict:
    """
    Pre-filters system_coords to a bounding cube around (x,y,z) — cheap,
    since system_coords has one row per system, not per station/commodity.
    Used to avoid market_prices' commodity_name index returning every
    station in the galaxy that ever sold a commodity (confirmed live:
    1.5-7.5s per commodity for a common one like Gold/Tritium — a
    station with 100+ commodities made Trade Opportunities take minutes)
    before most of those rows get thrown away for being out of range.
    Returns {system_name: (x, y, z)}; the cube is a loose superset of
    the sphere, so callers still need their own exact distance check.
    """
    rows = self.db.conn.execute(
        "SELECT system_name, x, y, z FROM system_coords "
        "WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?",
        (x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
    ).fetchall()
    return {r["system_name"]: (r["x"], r["y"], r["z"]) for r in rows}
```

- [ ] **Step 3: Rewrite `search_market_prices`**

Replace:

```python
def search_market_prices(
    self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> list[dict]:
    """
    Best sell prices for a commodity, filtered to radius_ly and joined
    against station_info for a confirmed landing pad size (from our own
    past visits, if any). Sorted with known pad size preferred over
    unknown, and best price within each tier — never silently
    recommends a destination we can't confirm you can physically dock
    at when a known-pad alternative exists. exclude_market_id skips a
    specific station (e.g. the one you're currently docked at).
    """
    coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
    if not coords_by_system:
        return []

    placeholders = ",".join("?" for _ in coords_by_system)
    rows = self.db.conn.execute(
        f"""
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.sell_price, m.demand, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction
        FROM market_prices m
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND m.system_name IN ({placeholders})
        """,
        (commodity_name, _market_data_cutoff(), *coords_by_system.keys()),
    ).fetchall()

    results = []
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = coords_by_system[r["system_name"]]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist

        # Ground truth from our own visits (if any) beats the EDDN-
        # reported stationType; both beat "?".
        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad

        results.append(rec)

    # Known pad size first, then best price within each tier.
    results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
    return results
```

With:

```python
def search_market_prices(
    self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> list[dict]:
    """
    Best sell prices for a commodity, filtered to radius_ly and joined
    against station_info for a confirmed landing pad size (from our own
    past visits, if any). Sorted with known pad size preferred over
    unknown, and best price within each tier — never silently
    recommends a destination we can't confirm you can physically dock
    at when a known-pad alternative exists. exclude_market_id skips a
    specific station (e.g. the one you're currently docked at).

    Filters system_coords via a bounding-box JOIN rather than fetching
    every nearby system name into Python first and binding one SQL
    parameter per name — system_coords is galaxy-wide and unbounded
    (fed continuously by the EDDN listener), and a per-name IN(...)
    list once exceeded SQLite's bound-parameter limit in production
    (~36k systems within a 200ly search). Bound-parameter count here
    is now fixed regardless of table size.
    """
    rows = self.db.conn.execute(
        """
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.sell_price, m.demand, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
               sc.x, sc.y, sc.z
        FROM market_prices m
        INNER JOIN system_coords sc ON sc.system_name = m.system_name
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
        """,
        (
            commodity_name, _market_data_cutoff(),
            x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
        ),
    ).fetchall()

    results = []
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = r["x"], r["y"], r["z"]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist

        # Ground truth from our own visits (if any) beats the EDDN-
        # reported stationType; both beat "?".
        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad

        results.append(rec)

    # Known pad size first, then best price within each tier.
    results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
    return results
```

- [ ] **Step 4: Rewrite `search_market_prices_multi`**

Replace:

```python
def search_market_prices_multi(
    self, commodity_names: list[str], x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> dict[str, list[dict]]:
    """
    Same as search_market_prices, but for many commodities in a single
    query — used by Trade Opportunities, which otherwise ran one
    search_market_prices call per purchasable commodity at a station
    (confirmed live: 100+ commodities x ~1s+ each made it take minutes).
    Returns {commodity_name: [results sorted best-first]}, same shape
    per-commodity as search_market_prices.
    """
    if not commodity_names:
        return {}

    coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
    if not coords_by_system:
        return {name: [] for name in commodity_names}

    sys_placeholders = ",".join("?" for _ in coords_by_system)
    commodity_placeholders = ",".join("?" for _ in commodity_names)
    rows = self.db.conn.execute(
        f"""
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.commodity_name, m.sell_price, m.demand, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large
        FROM market_prices m
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name IN ({commodity_placeholders}) AND m.sell_price IS NOT NULL
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND m.system_name IN ({sys_placeholders})
        """,
        (*commodity_names, _market_data_cutoff(), *coords_by_system.keys()),
    ).fetchall()

    by_commodity: dict[str, list[dict]] = {name: [] for name in commodity_names}
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = coords_by_system[r["system_name"]]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist
        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad
        by_commodity[rec["commodity_name"]].append(rec)

    for name, results in by_commodity.items():
        results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
    return by_commodity
```

With:

```python
def search_market_prices_multi(
    self, commodity_names: list[str], x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> dict[str, list[dict]]:
    """
    Same as search_market_prices, but for many commodities in a single
    query — used by Trade Opportunities, which otherwise ran one
    search_market_prices call per purchasable commodity at a station
    (confirmed live: 100+ commodities x ~1s+ each made it take minutes).
    Returns {commodity_name: [results sorted best-first]}, same shape
    per-commodity as search_market_prices.

    Filters system_coords via a bounding-box JOIN — see search_market_prices
    for why (bound-parameter count independent of table size).
    """
    if not commodity_names:
        return {}

    commodity_placeholders = ",".join("?" for _ in commodity_names)
    rows = self.db.conn.execute(
        f"""
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.commodity_name, m.sell_price, m.demand, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large,
               sc.x, sc.y, sc.z
        FROM market_prices m
        INNER JOIN system_coords sc ON sc.system_name = m.system_name
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name IN ({commodity_placeholders}) AND m.sell_price IS NOT NULL
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
        """,
        (
            *commodity_names, _market_data_cutoff(),
            x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
        ),
    ).fetchall()

    by_commodity: dict[str, list[dict]] = {name: [] for name in commodity_names}
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = r["x"], r["y"], r["z"]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist
        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad
        by_commodity[rec["commodity_name"]].append(rec)

    for name, results in by_commodity.items():
        results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
    return by_commodity
```

- [ ] **Step 5: Rewrite `search_fleet_carrier_materials`**

Replace:

```python
def search_fleet_carrier_materials(
    self, material_symbols: list[str], x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> dict[str, list[dict]]:
    """
    For each symbol in material_symbols, the nearby Fleet Carriers
    currently selling it, closest first. A carrier only appears if we
    have a station_info row for its market_id (from a Docked sighting,
    ours or another commander's via EDDN) -- fcmaterials_journal itself
    carries no location, so this INNER JOIN is the only way to place a
    carrier at all; one with no such row is silently excluded, never
    shown with an unknown location.
    """
    if not material_symbols:
        return {}

    coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
    if not coords_by_system:
        return {sym: [] for sym in material_symbols}

    sys_placeholders = ",".join("?" for _ in coords_by_system)
    sym_placeholders = ",".join("?" for _ in material_symbols)
    rows = self.db.conn.execute(
        f"""
        SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
               fcm.stock, fcm.demand, fcm.last_updated,
               si.market_id, si.system_name, si.last_visited
        FROM fleet_carrier_materials fcm
        INNER JOIN station_info si ON si.market_id = fcm.market_id
        WHERE fcm.material_symbol IN ({sym_placeholders})
              AND fcm.stock > 0
              AND fcm.last_updated >= ?
              AND si.system_name IN ({sys_placeholders})
        """,
        (*material_symbols, _fleet_carrier_cutoff(), *coords_by_system.keys()),
    ).fetchall()

    by_symbol: dict[str, list[dict]] = {sym: [] for sym in material_symbols}
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = coords_by_system[r["system_name"]]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist
        by_symbol[r["material_symbol"]].append(rec)

    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda r: r["distance_ly"])
    return by_symbol
```

With:

```python
def search_fleet_carrier_materials(
    self, material_symbols: list[str], x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> dict[str, list[dict]]:
    """
    For each symbol in material_symbols, the nearby Fleet Carriers
    currently selling it, closest first. A carrier only appears if we
    have a station_info row for its market_id (from a Docked sighting,
    ours or another commander's via EDDN) -- fcmaterials_journal itself
    carries no location, so this INNER JOIN is the only way to place a
    carrier at all; one with no such row is silently excluded, never
    shown with an unknown location.

    Filters system_coords via a bounding-box JOIN — see search_market_prices
    for why (bound-parameter count independent of table size; this was
    the function that actually crashed in production with "too many
    SQL variables" once system_coords passed ~33k systems in-radius).
    """
    if not material_symbols:
        return {}

    sym_placeholders = ",".join("?" for _ in material_symbols)
    rows = self.db.conn.execute(
        f"""
        SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
               fcm.stock, fcm.demand, fcm.last_updated,
               si.market_id, si.system_name, si.last_visited,
               sc.x, sc.y, sc.z
        FROM fleet_carrier_materials fcm
        INNER JOIN station_info si ON si.market_id = fcm.market_id
        INNER JOIN system_coords sc ON sc.system_name = si.system_name
        WHERE fcm.material_symbol IN ({sym_placeholders})
              AND fcm.stock > 0
              AND fcm.last_updated >= ?
              AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
        """,
        (
            *material_symbols, _fleet_carrier_cutoff(),
            x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
        ),
    ).fetchall()

    by_symbol: dict[str, list[dict]] = {sym: [] for sym in material_symbols}
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = r["x"], r["y"], r["z"]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist
        by_symbol[r["material_symbol"]].append(rec)

    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda r: r["distance_ly"])
    return by_symbol
```

- [ ] **Step 6: Rewrite `search_market_buy_prices`**

Replace:

```python
def search_market_buy_prices(
    self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> list[dict]:
    """
    Cheapest buy prices for a commodity — the mirror of
    search_market_prices, sorted ascending instead of descending, and
    requiring stock > 0 since a listed buy_price with nothing in stock
    isn't actually purchasable.
    """
    coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
    if not coords_by_system:
        return []

    placeholders = ",".join("?" for _ in coords_by_system)
    rows = self.db.conn.execute(
        f"""
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.buy_price, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction
        FROM market_prices m
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name = ? AND m.buy_price IS NOT NULL AND m.buy_price > 0
              AND m.stock IS NOT NULL AND m.stock > 0
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND m.system_name IN ({placeholders})
        """,
        (commodity_name, _market_data_cutoff(), *coords_by_system.keys()),
    ).fetchall()

    results = []
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = coords_by_system[r["system_name"]]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist

        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad

        results.append(rec)

    # Known pad size first, then cheapest price within each tier.
    results.sort(key=lambda r: (not r["pad_known"], r["buy_price"]))
    return results
```

With:

```python
def search_market_buy_prices(
    self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
    exclude_market_id: Optional[int] = None,
) -> list[dict]:
    """
    Cheapest buy prices for a commodity — the mirror of
    search_market_prices, sorted ascending instead of descending, and
    requiring stock > 0 since a listed buy_price with nothing in stock
    isn't actually purchasable.

    Filters system_coords via a bounding-box JOIN — see search_market_prices
    for why (bound-parameter count independent of table size).
    """
    rows = self.db.conn.execute(
        """
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.buy_price, m.stock, m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
               sc.x, sc.y, sc.z
        FROM market_prices m
        INNER JOIN system_coords sc ON sc.system_name = m.system_name
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE m.commodity_name = ? AND m.buy_price IS NOT NULL AND m.buy_price > 0
              AND m.stock IS NOT NULL AND m.stock > 0
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
        """,
        (
            commodity_name, _market_data_cutoff(),
            x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
        ),
    ).fetchall()

    results = []
    for r in rows:
        if exclude_market_id is not None and r["market_id"] == exclude_market_id:
            continue
        rx, ry, rz = r["x"], r["y"], r["z"]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue
        rec = dict(r)
        rec["distance_ly"] = dist

        pad = effective_pad_size(
            rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
        )
        rec["pad_known"] = pad != "?"
        rec["pad_size"] = pad

        results.append(rec)

    # Known pad size first, then cheapest price within each tier.
    results.sort(key=lambda r: (not r["pad_known"], r["buy_price"]))
    return results
```

- [ ] **Step 7: Rewrite `get_market_snapshot_in_radius`**

Replace:

```python
def get_market_snapshot_in_radius(self, x: float, y: float, z: float, radius_ly: float) -> dict[int, dict]:
    """
    Every station's full buy/sell commodity list within radius_ly, in
    one query — for the Trade Route Loop Planner, which needs to pair
    stations up (does A sell what B buys, and vice versa) rather than
    look up one commodity at a time. One query beats N here for the
    same reason search_market_prices_multi beat looping
    search_market_prices per commodity for Trade Opportunities.

    Returns {market_id: {"station_name", "system_name", "pad_size",
    "controlling_faction", "x", "y", "z", "distance_ly",
    "sells": {commodity: (sell_price, demand, last_updated)},
    "buys": {commodity: (buy_price, stock, last_updated)}}} — station
    metadata repeated per row collapses to one entry per market_id.
    last_updated (ISO timestamp string) lets callers judge/warn on
    crowdsourced-data staleness per commodity, not just per station.
    """
    coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
    if not coords_by_system:
        return {}

    placeholders = ",".join("?" for _ in coords_by_system)
    rows = self.db.conn.execute(
        f"""
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.commodity_name, m.sell_price, m.demand, m.buy_price, m.stock,
               m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction
        FROM market_prices m
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE (m.sell_price IS NOT NULL
                 OR (m.buy_price IS NOT NULL AND m.buy_price > 0 AND m.stock IS NOT NULL AND m.stock > 0))
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND m.system_name IN ({placeholders})
        """,
        (_market_data_cutoff(), *coords_by_system.keys()),
    ).fetchall()

    stations: dict[int, dict] = {}
    for r in rows:
        rx, ry, rz = coords_by_system[r["system_name"]]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue

        market_id = r["market_id"]
        station = stations.get(market_id)
        if station is None:
            pad = effective_pad_size(
                r["station_type"], r["pads_small"], r["pads_medium"], r["pads_large"]
            )
            station = {
                "station_name": r["station_name"],
                "system_name": r["system_name"],
                "pad_size": pad,
                "controlling_faction": r["station_faction"],
                "x": rx, "y": ry, "z": rz,
                "distance_ly": dist,
                "sells": {}, "buys": {},
            }
            stations[market_id] = station

        commodity = r["commodity_name"]
        if r["sell_price"] is not None:
            station["sells"][commodity] = (r["sell_price"], r["demand"], r["last_updated"])
        # stock > 0 required — a listed buy_price with nothing in
        # stock isn't actually purchasable (confirmed live: a
        # recommended return-leg commodity wasn't actually available
        # at the station, since this check was missing here, unlike
        # the equivalent check already in search_market_buy_prices).
        if r["buy_price"] is not None and r["buy_price"] > 0 and r["stock"] is not None and r["stock"] > 0:
            station["buys"][commodity] = (r["buy_price"], r["stock"], r["last_updated"])

    return stations
```

With:

```python
def get_market_snapshot_in_radius(self, x: float, y: float, z: float, radius_ly: float) -> dict[int, dict]:
    """
    Every station's full buy/sell commodity list within radius_ly, in
    one query — for the Trade Route Loop Planner, which needs to pair
    stations up (does A sell what B buys, and vice versa) rather than
    look up one commodity at a time. One query beats N here for the
    same reason search_market_prices_multi beat looping
    search_market_prices per commodity for Trade Opportunities.

    Returns {market_id: {"station_name", "system_name", "pad_size",
    "controlling_faction", "x", "y", "z", "distance_ly",
    "sells": {commodity: (sell_price, demand, last_updated)},
    "buys": {commodity: (buy_price, stock, last_updated)}}} — station
    metadata repeated per row collapses to one entry per market_id.
    last_updated (ISO timestamp string) lets callers judge/warn on
    crowdsourced-data staleness per commodity, not just per station.

    Filters system_coords via a bounding-box JOIN — see search_market_prices
    for why (bound-parameter count independent of table size).
    """
    rows = self.db.conn.execute(
        """
        SELECT m.market_id, m.station_name, m.station_type, m.system_name,
               m.commodity_name, m.sell_price, m.demand, m.buy_price, m.stock,
               m.last_updated,
               si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
               sc.x, sc.y, sc.z
        FROM market_prices m
        INNER JOIN system_coords sc ON sc.system_name = m.system_name
        LEFT JOIN station_info si ON si.market_id = m.market_id
        WHERE (m.sell_price IS NOT NULL
                 OR (m.buy_price IS NOT NULL AND m.buy_price > 0 AND m.stock IS NOT NULL AND m.stock > 0))
              AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
              AND m.last_updated >= ?
              AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
        """,
        (
            _market_data_cutoff(),
            x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
        ),
    ).fetchall()

    stations: dict[int, dict] = {}
    for r in rows:
        rx, ry, rz = r["x"], r["y"], r["z"]
        dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
        if dist > radius_ly:
            continue

        market_id = r["market_id"]
        station = stations.get(market_id)
        if station is None:
            pad = effective_pad_size(
                r["station_type"], r["pads_small"], r["pads_medium"], r["pads_large"]
            )
            station = {
                "station_name": r["station_name"],
                "system_name": r["system_name"],
                "pad_size": pad,
                "controlling_faction": r["station_faction"],
                "x": rx, "y": ry, "z": rz,
                "distance_ly": dist,
                "sells": {}, "buys": {},
            }
            stations[market_id] = station

        commodity = r["commodity_name"]
        if r["sell_price"] is not None:
            station["sells"][commodity] = (r["sell_price"], r["demand"], r["last_updated"])
        # stock > 0 required — a listed buy_price with nothing in
        # stock isn't actually purchasable (confirmed live: a
        # recommended return-leg commodity wasn't actually available
        # at the station, since this check was missing here, unlike
        # the equivalent check already in search_market_buy_prices).
        if r["buy_price"] is not None and r["buy_price"] > 0 and r["stock"] is not None and r["stock"] > 0:
            station["buys"][commodity] = (r["buy_price"], r["stock"], r["last_updated"])

    return stations
```

- [ ] **Step 8: Add the new index method to `persistence/database.py`**

Read the file fresh first to confirm `ensure_market_prices_indexes()`'s exact current location and text (it's a standalone method, not part of `run_migrations()`). Add a new sibling method directly after it:

```python
def ensure_system_coords_indexes(self) -> None:
    """system_coords has no index besides its PRIMARY KEY (system_name)
    — every radius search (Market, Fleet Carrier Materials, Trade Route
    Loop Planner) does a bounding-box JOIN against x/y/z with nothing to
    narrow the row set first. Not run from run_migrations() (which runs
    synchronously on the main/UI thread every startup) for the same
    reason ensure_market_prices_indexes() isn't: system_coords is fed
    continuously by the EDDN listener and grows unboundedly (437k+ rows
    and climbing as of this writing) — an index build at that scale, or
    whatever scale it reaches later, could freeze app launch. IF NOT
    EXISTS makes every run after the first an instant no-op. Call from
    a worker thread only, same reasoning as ensure_market_prices_indexes()."""
    self.conn.execute("CREATE INDEX IF NOT EXISTS idx_system_coords_xyz ON system_coords(x, y, z)")
```

- [ ] **Step 9: Wire the new index method into `_MarketVacuumWorker.run()`**

Read `edc/ui/main_window.py` fresh to confirm `_MarketVacuumWorker.run()`'s exact current text (it's the class right after `_MarketPruneWorker`). It currently reads:

```python
def run(self):
    from persistence.database import Database

    db = Database(self._db_path)
    try:
        ran_full_vacuum = db.enable_incremental_auto_vacuum()
        db.incremental_vacuum()
        db.ensure_market_prices_indexes()
        note = " (first run — also switched to incremental auto-vacuum)" if ran_full_vacuum else ""
        self.finished.emit(True, f"Database compacted{note}.")
    except Exception as exc:
        log.exception("Database compaction failed")
        self.finished.emit(False, f"Compaction failed: {exc}")
    finally:
        db.close()
```

Add one line after `db.ensure_market_prices_indexes()`:

```python
def run(self):
    from persistence.database import Database

    db = Database(self._db_path)
    try:
        ran_full_vacuum = db.enable_incremental_auto_vacuum()
        db.incremental_vacuum()
        db.ensure_market_prices_indexes()
        db.ensure_system_coords_indexes()
        note = " (first run — also switched to incremental auto-vacuum)" if ran_full_vacuum else ""
        self.finished.emit(True, f"Database compacted{note}.")
    except Exception as exc:
        log.exception("Database compaction failed")
        self.finished.emit(False, f"Compaction failed: {exc}")
    finally:
        db.close()
```

- [ ] **Step 10: Add the crash-regression test to `tests/test_fleet_carrier_materials.py`**

Read the file fresh first to confirm the exact current `repo` fixture and `_seed_station`/`_seed_coords`/`_seed_material` helper signatures (shown in this plan's context match what's there as of writing this plan — re-confirm before editing). Add this test at the end of the file:

```python
def test_search_succeeds_with_more_systems_than_old_sqlite_variable_limit(repo):
    # Regression test for the production crash this fix addresses:
    # sqlite3.OperationalError: too many SQL variables. The OLD
    # implementation built one SQL bound parameter per system_coords row
    # inside the search radius; with system_coords fed continuously and
    # unboundedly by the EDDN listener, a real search once had to bind
    # 36,148 parameters against this build's 32,766 limit
    # (conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)). Seed comfortably
    # past that limit here so this test would fail with that exact
    # OperationalError against the pre-fix code, and passes against the
    # JOIN-based rewrite (whose bound-parameter count doesn't grow with
    # table size at all).
    dummy_coords = [
        (f"Dummy System {i}", float(i % 100), float((i // 100) % 100), float(i // 10000), "2026-08-12T00:00:00Z")
        for i in range(33_000)
    ]
    repo.save_system_coords_batch(dummy_coords)

    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 2000.0)

    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["carrier_name"] == "Test Carrier"
```

- [ ] **Step 11: Run the new fleet-carrier tests**

Run: `pytest tests/test_fleet_carrier_materials.py -v`
Expected: all tests pass, including the new `test_search_succeeds_with_more_systems_than_old_sqlite_variable_limit` and the pre-existing `test_uses_inner_join_against_station_info_not_left_join` (confirming the `INNER JOIN station_info` wording survived the rewrite).

- [ ] **Step 12: Create `tests/test_market_radius_queries.py`**

Read `persistence/repository.py`'s `save_system_coords_batch` and `save_market_snapshot_batch` fresh (confirm exact tuple field order) before writing this file. Read `tests/test_fleet_carrier_materials.py`'s `repo` fixture fresh and reuse the identical pattern:

```python
"""Tests for the 4 radius-based Repository search functions that read
system_coords via a JOIN (search_market_prices, search_market_prices_multi,
search_market_buy_prices, get_market_snapshot_in_radius) -- real SQLite
(temp file), not mocks. These functions had no test coverage before this
file; the tests here are safety nets for the IN-list -> JOIN rewrite
(behavior must not change), not TDD-red tests."""
import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_market_row(
    repo, market_id, commodity_name, system_name, station_name="Test Station",
    station_type="Coriolis", sell_price=1000, buy_price=None, mean_price=1000,
    demand=0, demand_bracket=0, stock=None, stock_bracket=0,
    last_updated="2026-08-12T00:00:00Z",
):
    repo.save_market_snapshot_batch([(
        market_id, commodity_name, station_name, station_type, system_name,
        sell_price, buy_price, mean_price, demand, demand_bracket,
        stock, stock_bracket, last_updated,
    )])


# ---- search_market_prices ----

def test_search_market_prices_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert len(results) == 1
    assert results[0]["system_name"] == "Sol"
    assert results[0]["sell_price"] == 5000


def test_search_market_prices_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert results == []


def test_search_market_prices_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert results == []


# ---- search_market_prices_multi ----

def test_search_market_prices_multi_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    by_commodity = repo.search_market_prices_multi(["gold", "silver"], 0.0, 0.0, 0.0, 50.0)
    assert len(by_commodity["gold"]) == 1
    assert by_commodity["silver"] == []


def test_search_market_prices_multi_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    by_commodity = repo.search_market_prices_multi(["gold"], 0.0, 0.0, 0.0, 50.0)
    assert by_commodity["gold"] == []


def test_search_market_prices_multi_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    by_commodity = repo.search_market_prices_multi(["gold"], 0.0, 0.0, 0.0, 50.0)
    assert by_commodity["gold"] == []


# ---- search_market_buy_prices ----

def test_search_market_buy_prices_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "tritium", "Sol", sell_price=None, buy_price=8000, stock=500)

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert len(results) == 1
    assert results[0]["buy_price"] == 8000


def test_search_market_buy_prices_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "tritium", "Far System", sell_price=None, buy_price=8000, stock=500)

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert results == []


def test_search_market_buy_prices_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(
        repo, 1001, "tritium", "Sol", sell_price=None, buy_price=8000, stock=500,
        last_updated="2026-01-01T00:00:00Z",
    )

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert results == []


# ---- get_market_snapshot_in_radius ----

def test_get_market_snapshot_in_radius_finds_station_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert 1001 in snapshot
    assert snapshot[1001]["sells"]["gold"] == (5000, 0, "2026-08-12T00:00:00Z")


def test_get_market_snapshot_in_radius_excludes_station_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert snapshot == {}


def test_get_market_snapshot_in_radius_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert snapshot == {}
```

- [ ] **Step 13: Run the new market radius query tests**

Run: `pytest tests/test_market_radius_queries.py -v`
Expected: all 9 tests pass.

- [ ] **Step 14: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests pass (this rewrite touches shared, widely-used repository functions — confirm nothing else broke, e.g. Trade Opportunities/Trade Route Loop Planner code that calls these functions indirectly through other modules).

- [ ] **Step 15: Commit**

```bash
git add persistence/repository.py persistence/database.py edc/ui/main_window.py tests/test_fleet_carrier_materials.py tests/test_market_radius_queries.py
git commit -m "fix: replace unbounded IN-list with JOIN in radius-search queries

sqlite3.OperationalError: too many SQL variables crashed Fleet Carrier
material search once system_coords (fed continuously by the EDDN
listener, unbounded) grew past ~33k systems within the configured
search radius. All 5 radius-search functions now filter system_coords
via a bounding-box JOIN instead of binding one SQL parameter per
system name, so bound-parameter count no longer scales with table
size. Adds a worker-triggered index (idx_system_coords_xyz) for query
speed, built the same way the existing market_prices index already is
-- not on the auto-run startup migration path, to avoid ever freezing
app launch as this table keeps growing."
```

---

### Task 2: Prune stale fleet_carrier_materials rows

**Files:**
- Modify: `persistence/repository.py` (add `prune_stale_fleet_carrier_materials`)
- Modify: `edc/ui/main_window.py` (wire into `_MarketPruneWorker.run()`)
- Test: `tests/test_fleet_carrier_materials.py`

**Interfaces:**
- Consumes: existing `_fleet_carrier_cutoff()` (module-level function in `persistence/repository.py`, already used by `search_fleet_carrier_materials`), existing `Repository.save_fleet_carrier_materials_batch(records: list[tuple])`.
- Produces: `Repository.prune_stale_fleet_carrier_materials(self) -> int`, consumed by this task's own `_MarketPruneWorker.run()` change (no other task depends on it).

- [ ] **Step 1: Write the failing test**

Read `tests/test_fleet_carrier_materials.py` fresh to confirm the exact current `repo` fixture and `_seed_station`/`_seed_coords`/`_seed_material` helpers, then add:

```python
def test_prune_stale_fleet_carrier_materials_deletes_only_rows_past_7_day_cutoff(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", last_updated="2026-08-14T00:00:00Z")  # fresh, within 7 days
    _seed_material(repo, 1001, "geneticrepairmeds", last_updated="2026-07-01T00:00:00Z")  # stale

    deleted = repo.prune_stale_fleet_carrier_materials()

    assert deleted == 1
    remaining = repo.db.conn.execute(
        "SELECT material_symbol FROM fleet_carrier_materials"
    ).fetchall()
    assert [r["material_symbol"] for r in remaining] == ["graphene"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fleet_carrier_materials.py::test_prune_stale_fleet_carrier_materials_deletes_only_rows_past_7_day_cutoff -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'prune_stale_fleet_carrier_materials'`

- [ ] **Step 3: Implement `prune_stale_fleet_carrier_materials`**

Read `persistence/repository.py`'s `prune_stale_market_prices` fresh to confirm its exact current text (it's the method right before the radius-search functions touched in Task 1):

```python
def prune_stale_market_prices(self) -> int:
    """
    Deletes rows already excluded from search results by
    _market_data_cutoff() — a stale row is dead weight once nothing
    can ever surface it, not just hidden. Same 30-day threshold as the
    search filter, so this doesn't change what search can find, only
    what's still sitting on disk. Call from a worker thread only — a
    DELETE across the whole market_prices table is not instant at
    galaxy-wide scale (millions of rows)."""
    cur = self.db.conn.execute(
        "DELETE FROM market_prices WHERE last_updated < ?",
        (_market_data_cutoff(),),
    )
    self.db.conn.commit()
    return cur.rowcount
```

Add a new sibling method directly after it:

```python
def prune_stale_fleet_carrier_materials(self) -> int:
    """
    Deletes rows already excluded from search results by
    _fleet_carrier_cutoff() — same reasoning as prune_stale_market_prices():
    a stale row is dead weight once nothing can ever surface it, not
    just hidden. Same 7-day threshold as the search filter, so this
    doesn't change what search can find, only what's still sitting on
    disk. Call from a worker thread only."""
    cur = self.db.conn.execute(
        "DELETE FROM fleet_carrier_materials WHERE last_updated < ?",
        (_fleet_carrier_cutoff(),),
    )
    self.db.conn.commit()
    return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fleet_carrier_materials.py::test_prune_stale_fleet_carrier_materials_deletes_only_rows_past_7_day_cutoff -v`
Expected: PASS

- [ ] **Step 5: Wire the new prune method into `_MarketPruneWorker.run()`**

Read `edc/ui/main_window.py` fresh to confirm `_MarketPruneWorker.run()`'s exact current text (near line 174, immediately before `_MarketVacuumWorker`). It currently reads:

```python
def run(self):
    from persistence.database import Database
    from persistence.repository import Repository

    db = Database(self._db_path)
    deleted = 0
    try:
        repo = Repository(db)
        deleted = repo.prune_stale_market_prices()
    except Exception:
        log.exception("Market prices prune failed")
    finally:
        db.close()
    self.finished.emit(deleted)
```

Replace with:

```python
def run(self):
    from persistence.database import Database
    from persistence.repository import Repository

    db = Database(self._db_path)
    deleted_market_prices = 0
    deleted_fleet_carrier_materials = 0
    try:
        repo = Repository(db)
        try:
            deleted_market_prices = repo.prune_stale_market_prices()
            log.info("Pruned %d stale market_prices rows", deleted_market_prices)
        except Exception:
            log.exception("Market prices prune failed")
        try:
            deleted_fleet_carrier_materials = repo.prune_stale_fleet_carrier_materials()
            log.info("Pruned %d stale fleet_carrier_materials rows", deleted_fleet_carrier_materials)
        except Exception:
            log.exception("Fleet carrier materials prune failed")
    finally:
        db.close()
    self.finished.emit(deleted_market_prices + deleted_fleet_carrier_materials)
```

`_on_market_prune_finished` (the `finished` signal's connected slot) needs no change — it already just logs the total and updates `cfg.last_market_prune_date`, and the signal's signature (`pyqtSignal(int)`) is unchanged.

- [ ] **Step 6: Run the full fleet-carrier test file**

Run: `pytest tests/test_fleet_carrier_materials.py -v`
Expected: all tests pass, including both new tests from Task 1 Step 10 and this task's Step 1.

- [ ] **Step 7: Commit**

```bash
git add persistence/repository.py edc/ui/main_window.py tests/test_fleet_carrier_materials.py
git commit -m "fix: prune stale fleet_carrier_materials rows like market_prices already does

fleet_carrier_materials rows were filtered out of search results past
the existing 7-day cutoff but never deleted -- unbounded disk growth,
same class of gap system_coords had before the JOIN rewrite, just
slower since carrier sightings are rarer than galaxy-wide system
traffic. Runs from the same daily background worker that already
prunes market_prices."
```

- [ ] **Step 8: Manual live verification**

Start the app. In `settings/settings.json`, remove or backdate `last_market_prune_date` to force the daily prune to fire (or wait until the date naturally rolls over). Confirm the log shows both a `Pruned N stale market_prices rows` line and a `Pruned N stale fleet_carrier_materials rows` line. Separately, re-trigger the original crash scenario (Engineering tab → Wishlist card → select a wishlist entry with an unmet material requirement) and confirm the Fleet Carrier search now completes without an exception in the log.
