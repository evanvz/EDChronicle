# Fleet Carrier Docking Access Filter — Design

## Context

The Engineering tab's "SOLD BY CARRIERS — CLOSEST FIRST" tables (Ships tab
and Suits & Weapons tab, both in `edc/ui/panels/engineering_panel.py`) list
other commanders' Fleet Carriers selling engineering materials, sourced
from EDDN's `fcmaterials_journal/1` schema via
`Repository.search_fleet_carrier_materials()` (`persistence/repository.py:1486`).

Confirmed by direct code/schema research (not assumed):

- `fcmaterials_journal/1` carries only `MarketID`, `CarrierName`,
  `CarrierID`, `Items[]` — no location, no docking-access field at all
  (verified against EDCD/EDDN's schema repo, per
  `docs/superpowers/specs/2026-08-12-fleet-carrier-materials-design.md`).
  Location comes from an `INNER JOIN` to `station_info`, populated from
  `Docked` journal events (ours or others' via EDDN `commodity/3`).
- Real `DockingAccess` (`all`/`friends`/`squadron`/`squadronfriends`/`none`)
  only ever appears in `CarrierStats`, a **private** journal event that
  fires only for the player's own carrier — confirmed via a repo-wide grep,
  never observable for someone else's carrier via EDDN or journal.
- The **only** signal that can ever answer "can I land on this specific
  other commander's carrier" is `commodity/3`'s optional
  `carrierDockingAccess` field, which a carrier owner's client may
  self-report when publishing their market. Not currently captured by
  `edc/core/eddn_market.py::on_commodity_message()` (line 56). Coverage is
  necessarily incomplete: only present when the owner both publishes
  commodity data to EDDN and their client sets that field.

Given this, most carriers will have **no** docking-access signal at all —
not restricted, just unknown. Per user decision: unknown carriers still
show (labeled), only *confirmed*-restricted carriers are excluded.

## Design

### Ingestion — `edc/core/eddn_market.py`

New 7th buffer, mirroring the existing six (`_coord_buffer`,
`_market_buffer`, `_faction_buffer`, `_station_buffer`, `_codex_buffer`,
`_fcmaterials_buffer`):

```python
self._carrier_access_buffer: Dict[int, tuple] = {}  # keyed by market_id
```

`on_commodity_message()` (already runs per commodity message) gains, after
its existing field reads:

```python
docking_access = msg.get("carrierDockingAccess")
if isinstance(docking_access, str) and docking_access:
    self._carrier_access_buffer[market_id] = (market_id, docking_access, timestamp)
```

Folded into `buffered_counts()`, `pop_buffers()`, `flush()`, and
`write_buffers()` exactly like the other six buffers (7-tuple instead of
6-tuple return/parameters throughout — every call site listed above must
be updated together, including `main_window.py`'s `_EddnFlushWorker` and
its `pop_buffers()`/`write_buffers()` call sites).

### Schema — `persistence/database.py`

New migration line, following the existing `ALTER TABLE ... ADD COLUMN`
precedent (each migration already runs in its own try/except, silently
ignoring "column already exists"):

```python
"ALTER TABLE station_info ADD COLUMN carrier_docking_access TEXT",
```

`station_info` is the right home for this — it's already one row per
`market_id` (its `PRIMARY KEY`), the same granularity as docking access
(a per-carrier fact, not per-commodity). No new table.

### Repository — `persistence/repository.py`

New method, mirroring `save_fleet_carrier_materials_batch`'s upsert shape:

```python
def save_carrier_docking_access_batch(self, records: list[tuple]):
    """
    records: [(market_id, docking_access, timestamp), ...]
    Upserts only the carrier_docking_access column -- if no station_info
    row exists yet for this market_id (no Docked sighting seen), inserts
    a skeletal row with just market_id + this column; a later Docked
    sighting's own upsert (save_station_info_batch) fills in the rest
    without touching this column. Harmless either order.
    """
    if not records:
        return
    cur = self.db.conn.cursor()
    cur.executemany(
        """
        INSERT INTO station_info (market_id, carrier_docking_access)
        VALUES (?, ?)
        ON CONFLICT(market_id) DO UPDATE SET
            carrier_docking_access = excluded.carrier_docking_access
        """,
        [(market_id, access) for market_id, access, _ts in records],
    )
    self.db.conn.commit()
```

`search_fleet_carrier_materials()` changes:
- `SELECT` gains `si.carrier_docking_access`.
- `WHERE` gains `AND (si.carrier_docking_access IS NULL OR si.carrier_docking_access = 'all')` —
  excludes confirmed-restricted (`friends`/`squadron`/`squadronfriends`/`none`),
  keeps unknown (`NULL`) and confirmed-open (`'all'`).
- Each returned listing dict gains a `"docking_access"` key (the raw value,
  `None` or `"all"` after this filter — nothing else can reach the caller).

### UI — `edc/ui/panels/engineering_panel.py`

Both carrier tables (Ships tab: header/table setup at lines 311-324,
populated by `_refresh_carrier_table` at lines 606-681; Suits & Weapons
tab: identical structure at lines 856-869 and 1118-~1190) gain an "Access"
column:

- `_make_table([...])` header list gains `"Access"` as an 8th column
  (after "Age"), with `ResizeToContents` like the other status-ish columns.
- Per-row: `access_item = QTableWidgetItem("Open" if listing.get("docking_access") == "all" else "Unknown")`,
  colored via `setForeground(QColor("#6BCB77"))` for "Open" and
  `setForeground(QColor("#888888"))` for "Unknown" — this exact pairing
  (confirmed-good green / muted grey) is already established at
  `engineering_panel.py:1047-1050` for an analogous "confirmed source"
  vs "unknown source" cell, reused verbatim rather than inventing new hex
  values.
- The existing staleness note (`"Carrier listings/locations are
  crowdsourced from EDDN and can be several days old."`, present in both
  copies) gains one more sentence, appended once, not conditionally:
  `" Carriers with confirmed restricted access are filtered out; \"Unknown\" access is not guaranteed open."`

## Out of scope

- No change to the player's own carrier's docking-access display
  (`fleet_carrier_panel.py`) — that already works correctly from the
  private `CarrierStats` event, untouched by this plan.
- No staleness/freshness cutoff specific to `carrier_docking_access`
  beyond what already exists — a carrier's self-reported access can change
  at any time, and this data is opportunistic/rare already; the existing
  "Age" column and staleness note already communicate general
  crowdsourced-data caveats, and each new EDDN sighting naturally
  overwrites the stored value with the latest self-report (no explicit
  cutoff needed for a single-column upsert).
- No attempt to capture or reconcile `commodity/3`'s `carrierDockingAccess`
  for the player's own carrier — the player's own `fleet_carrier_panel.py`
  already has ground-truth from `CarrierStats`, more reliable than a
  self-published EDDN echo of the same fact.
