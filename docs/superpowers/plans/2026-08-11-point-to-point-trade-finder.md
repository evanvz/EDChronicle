# Point-to-Point Trade Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-way trade finder to the Trade Route tab — given the station you're currently docked at and a destination (typed manually, or auto-filled from the game's plotted route), find what to buy here and sell there for the best profit.

**Architecture:** Origin data comes from already-in-memory `state.current_market_items` (zero new query). A new, narrow repository method fetches the destination system's market data. A new pure function (same profit/capacity-capping formula as the existing Loop Planner's `_best_leg()`) ranks every profitable commodity across the destination's stations. A new card on the existing Trade Route tab wires it together, following that tab's existing worker-thread/table conventions exactly.

**Tech Stack:** Python, SQLite, PyQt6 (`QThread`/`QObject` worker pattern, `QTableWidget`), pytest.

## Global Constraints

- Origin commodity data source: `state.current_market_items` (list of `{"name", "category", "buy_price", "sell_price", "demand", "stock"}` dicts, already populated by `main_window.py::_load_current_market()` whenever the commodities screen is opened) — not a DB query.
- Destination auto-fill source: `state.route_target_system` (already populated by the existing `FSDTarget` handler in `event_engine.py:462-475`; cleared by `NavRouteClear`) — no new journal parsing.
- Cargo capacity source: `state.cargo_capacity` — same field the existing Loop Planner already uses.
- Commodity-name matching: `market_prices.commodity_name` stores normalized symbols (lowercase, no spaces/punctuation, e.g. `"lowtemperaturediamonds"`); `state.current_market_items`' `"name"` field is the display form (e.g. `"Low Temperature Diamonds"`). Normalize before matching. Per `trade_routes.py`'s own stated design principle ("no Qt, no DB, just data in/data out"), do NOT import `normalize_commodity_name()` from `edc/ui/panels/market_panel.py` (a UI-layer module) into `trade_routes.py` — duplicate the same 2-line regex locally there instead, keeping that module's dependency direction one-way.
- New UI card goes on the existing Trade Route tab (`edc/ui/panels/trade_route_panel.py`), as a second `QFrame` card in the same `TradeRoutePanel`, not a new tab or new panel class.
- No automated test for the new repository method or the UI wiring — matches this codebase's existing convention (the sibling `get_market_snapshot_in_radius()` has no dedicated test; no panel file has UI tests anywhere in this repo).

---

### Task 1: `find_point_to_point_trades()` — pure ranking function

**Files:**
- Modify: `edc/core/trade_routes.py`
- Test: `tests/test_trade_routes.py`

**Interfaces:**
- Produces: `find_point_to_point_trades(origin_items: List[Dict[str, Any]], destination_stations: Dict[int, dict], cargo_capacity: int, max_results: int = 10) -> List[Dict[str, Any]]`. `origin_items` is `state.current_market_items`'s shape. `destination_stations` is the shape `Repository.get_market_snapshot_for_systems()` (Task 2) returns — `{market_id: {"station_name", "system_name", "pad_size", "controlling_faction", "sells": {commodity_symbol: (sell_price, demand, last_updated)}, "buys": {...}}}`. Each result dict: `{"commodity", "sell_station_name", "sell_system_name", "buy_price", "sell_price", "profit_per_unit", "quantity", "total_profit", "data_age_hours"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_routes.py` (add this import alongside the existing one at the top of the file):

```python
from edc.core.trade_routes import find_trade_loops, find_point_to_point_trades
```

Then add these tests (place after the existing `test_swap_does_not_corrupt_later_pairings`, before the `if __name__ == "__main__":` block):

```python
def _origin_item(name, buy_price, stock):
    return {"name": name, "category": "", "buy_price": buy_price, "sell_price": 0, "demand": 0, "stock": stock}


def _dest_station(name, system, sells=None):
    return {
        "station_name": name, "system_name": system, "pad_size": 3,
        "controlling_faction": None, "sells": sells or {}, "buys": {},
    }


def test_point_to_point_finds_profitable_commodity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=500)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 200, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    r = results[0]
    assert r["commodity"] == "Platinum"
    assert r["sell_station_name"] == "Jameson Memorial"
    assert r["buy_price"] == 1000
    assert r["sell_price"] == 1500
    assert r["profit_per_unit"] == 500


def test_point_to_point_excludes_negative_margin():
    origin_items = [_origin_item("Platinum", buy_price=2000, stock=500)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 200, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert results == []


def test_point_to_point_caps_quantity_at_cargo_capacity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=5000)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 5000, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=64)
    assert results[0]["quantity"] == 64
    assert results[0]["total_profit"] == 500 * 64


def test_point_to_point_caps_quantity_at_stock_and_demand():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=10)]
    destination_stations = {
        1: _dest_station("Jameson Memorial", "Shinrarta Dezhra", sells={"platinum": (1500, 3, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=500)
    assert results[0]["quantity"] == 3  # demand is the tightest cap


def test_point_to_point_picks_best_station_for_same_commodity():
    origin_items = [_origin_item("Platinum", buy_price=1000, stock=500)]
    destination_stations = {
        1: _dest_station("Low Price Station", "System A", sells={"platinum": (1200, 500, _NOW)}),
        2: _dest_station("High Price Station", "System B", sells={"platinum": (1600, 500, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    assert results[0]["sell_station_name"] == "High Price Station"
    assert results[0]["profit_per_unit"] == 600


def test_point_to_point_truncates_to_max_results():
    origin_items = [
        _origin_item("Platinum", buy_price=1000, stock=100),
        _origin_item("Gold", buy_price=500, stock=100),
        _origin_item("Silver", buy_price=200, stock=100),
    ]
    destination_stations = {
        1: _dest_station("Station", "System", sells={
            "platinum": (1500, 100, _NOW),
            "gold": (900, 100, _NOW),
            "silver": (400, 100, _NOW),
        }),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100, max_results=2)
    assert len(results) == 2
    # sorted by total profit descending
    assert results[0]["total_profit"] >= results[1]["total_profit"]


def test_point_to_point_normalizes_commodity_names_for_matching():
    origin_items = [_origin_item("Low Temperature Diamonds", buy_price=1000, stock=100)]
    destination_stations = {
        1: _dest_station("Station", "System", sells={"lowtemperaturediamonds": (1500, 100, _NOW)}),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert len(results) == 1
    assert results[0]["commodity"] == "Low Temperature Diamonds"


def test_point_to_point_ignores_items_with_no_buy_price_or_stock():
    origin_items = [
        _origin_item("Platinum", buy_price=0, stock=500),      # not purchasable here
        _origin_item("Gold", buy_price=500, stock=0),          # nothing in stock
    ]
    destination_stations = {
        1: _dest_station("Station", "System", sells={
            "platinum": (1500, 100, _NOW), "gold": (900, 100, _NOW),
        }),
    }
    results = find_point_to_point_trades(origin_items, destination_stations, cargo_capacity=100)
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trade_routes.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_point_to_point_trades'`

- [ ] **Step 3: Implement `find_point_to_point_trades()`**

Add to `edc/core/trade_routes.py`, after the existing `_parse_ts()` function and before `find_trade_loops()`:

```python
import re


def _normalize_commodity_name(name: str) -> str:
    """Duplicated from edc/ui/panels/market_panel.py's identical function
    rather than imported -- this module is deliberately Qt/DB-free (see
    module docstring), and importing from a UI-layer module would run
    the dependency the wrong direction for two lines of regex."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def find_point_to_point_trades(
    origin_items: List[Dict[str, Any]],
    destination_stations: Dict[int, dict],
    cargo_capacity: int,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    For every commodity buyable at the origin (state.current_market_items
    shape), finds the best-selling destination station for it -- if the
    destination system has more than one station selling it -- and
    computes a cargo-capacity-capped total profit, same formula as
    _best_leg() uses for the Loop Planner. Commodities with no
    positive-margin destination are excluded entirely, not returned as
    zero/negative rows. Returns up to max_results, sorted by total
    profit descending.
    """
    results: List[Dict[str, Any]] = []

    for item in origin_items:
        display_name = item.get("name")
        buy_price = item.get("buy_price")
        stock = item.get("stock")
        if not isinstance(display_name, str) or not display_name:
            continue
        if not isinstance(buy_price, int) or buy_price <= 0:
            continue
        if not isinstance(stock, int) or stock <= 0:
            continue

        symbol = _normalize_commodity_name(display_name)
        best: Optional[Dict[str, Any]] = None

        for station in destination_stations.values():
            sell_info = station["sells"].get(symbol)
            if sell_info is None:
                continue
            sell_price, demand, last_updated = sell_info
            profit_per_unit = sell_price - buy_price
            if profit_per_unit <= 0:
                continue

            qty = cargo_capacity
            if isinstance(stock, int) and stock > 0:
                qty = min(qty, stock)
            if isinstance(demand, int) and demand > 0:
                qty = min(qty, demand)
            if qty <= 0:
                continue

            total = profit_per_unit * qty
            if best is None or total > best["total_profit"]:
                dt = _parse_ts(last_updated)
                age_hours = (
                    (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
                    if dt else None
                )
                best = {
                    "commodity": display_name,
                    "sell_station_name": station["station_name"],
                    "sell_system_name": station["system_name"],
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit_per_unit": profit_per_unit,
                    "quantity": qty,
                    "total_profit": total,
                    "data_age_hours": age_hours,
                }

        if best is not None:
            results.append(best)

    results.sort(key=lambda r: r["total_profit"], reverse=True)
    return results[:max_results]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_trade_routes.py -v`
Expected: PASS (9 passed — 1 existing + 8 new)

- [ ] **Step 5: Commit**

```bash
git add edc/core/trade_routes.py tests/test_trade_routes.py
git commit -m "feat: add find_point_to_point_trades() for origin-to-destination profit ranking"
```

---

### Task 2: `Repository.get_market_snapshot_for_systems()`

**Files:**
- Modify: `persistence/repository.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Repository.get_market_snapshot_for_systems(system_names: list[str]) -> dict[int, dict]` — same per-station shape as the existing `get_market_snapshot_in_radius()` minus the `x`/`y`/`z`/`distance_ly` fields (no reference point to measure distance from here).

No automated test for this task (matches Global Constraints — the sibling method has none either).

- [ ] **Step 1: Implement the method**

Add to `persistence/repository.py`, directly after the existing `get_market_snapshot_in_radius()` method (which ends around line 1423, right before `add_colonisation_depot_manual`):

```python
    def get_market_snapshot_for_systems(self, system_names: list[str]) -> dict[int, dict]:
        """
        Same per-station shape as get_market_snapshot_in_radius(), but
        filtered to an exact list of system names instead of radius+
        distance -- for the Point-to-Point trade finder, which already
        knows exactly which system it wants (the destination), not "give
        me everything nearby". No x/y/z/distance_ly in the output since
        there's no reference point to measure distance from here.

        Returns {market_id: {"station_name", "system_name", "pad_size",
        "controlling_faction", "sells": {commodity: (sell_price, demand,
        last_updated)}, "buys": {commodity: (buy_price, stock,
        last_updated)}}}.
        """
        if not system_names:
            return {}

        placeholders = ",".join("?" for _ in system_names)
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
            (_market_data_cutoff(), *system_names),
        ).fetchall()

        stations: dict[int, dict] = {}
        for r in rows:
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
                    "sells": {}, "buys": {},
                }
                stations[market_id] = station

            commodity = r["commodity_name"]
            if r["sell_price"] is not None:
                station["sells"][commodity] = (r["sell_price"], r["demand"], r["last_updated"])
            if r["buy_price"] is not None and r["buy_price"] > 0 and r["stock"] is not None and r["stock"] > 0:
                station["buys"][commodity] = (r["buy_price"], r["stock"], r["last_updated"])

        return stations
```

- [ ] **Step 2: Compile-check**

Run: `python -m py_compile persistence/repository.py`
Expected: no output (success)

- [ ] **Step 3: Commit**

```bash
git add persistence/repository.py
git commit -m "feat: Repository.get_market_snapshot_for_systems() for exact-system market lookups"
```

---

### Task 3: Point-to-Point card on the Trade Route tab

**Files:**
- Modify: `edc/ui/panels/trade_route_panel.py`

**Interfaces:**
- Consumes: `find_point_to_point_trades(origin_items, destination_stations, cargo_capacity, max_results=10)` (Task 1); `Repository.get_market_snapshot_for_systems(system_names)` (Task 2); `state.current_market_items`, `state.current_market_station`, `state.current_market_system`, `state.route_target_system`, `state.cargo_capacity` (all pre-existing `GameState` fields).
- Produces: nothing new for later tasks — this is the final task in this plan.

No automated test for this task (UI wiring, matches Global Constraints). Compile-check plus live verification.

- [ ] **Step 1: Add the import**

In `edc/ui/panels/trade_route_panel.py`, change the existing import line:

```python
from edc.core.trade_routes import find_trade_loops
```

to:

```python
from edc.core.trade_routes import find_trade_loops, find_point_to_point_trades
```

- [ ] **Step 2: Add the worker class**

Add directly after the existing `_TradeRouteWorker` class (which ends around line 103, right before `class TradeRoutePanel`):

```python
class _PointToPointWorker(QObject):
    """Mirrors _TradeRouteWorker's shape -- own SQLite connection per the
    project's cross-thread rule, one-shot per search click."""
    finished = pyqtSignal(list, str)  # (results, error)

    def __init__(self, db_path, origin_items, destination_system, cargo_capacity):
        super().__init__()
        self._db_path = db_path
        self._origin_items = origin_items
        self._destination_system = destination_system
        self._cargo_capacity = cargo_capacity

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            stations = repo.get_market_snapshot_for_systems([self._destination_system])
            if not stations:
                self.finished.emit([], f"No market data for {self._destination_system} yet.")
                return
            results = find_point_to_point_trades(
                self._origin_items, stations, self._cargo_capacity,
            )
        except Exception as exc:
            log.exception("Point-to-point trade search failed")
            self.finished.emit([], str(exc))
            return
        finally:
            db.close()
        self.finished.emit(results, "")
```

- [ ] **Step 3: Add instance state in `__init__`**

In `TradeRoutePanel.__init__`, directly after `self._worker: Optional[_TradeRouteWorker] = None` (around line 119), add:

```python
        self._origin_items: list = []
        self._origin_station: str = ""
        self._origin_system: str = ""
        self._route_target_system: str = ""
        self._dest_user_edited: bool = False
        self._p2p_thread: Optional[QThread] = None
        self._p2p_worker: Optional[_PointToPointWorker] = None
```

- [ ] **Step 4: Add the new card's widgets**

In `edc/ui/panels/trade_route_panel.py`, directly after the existing `root.addWidget(frame, 1)` (the line that closes off the Loop Planner card, around line 249) and before `def refresh(self, state) -> None:`, add:

```python
        p2p_frame = QFrame()
        p2p_frame.setStyleSheet(_CARD_STYLE)
        p2p_l = QVBoxLayout(p2p_frame)
        p2p_l.setContentsMargins(8, 6, 8, 8)
        p2p_l.setSpacing(6)

        p2p_hdr = QLabel("POINT-TO-POINT TRADE FINDER")
        p2p_hdr.setStyleSheet("color:#7a7a7a; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;")
        p2p_l.addWidget(p2p_hdr)

        p2p_note = QLabel(
            "What to buy here and sell at a specific destination -- the destination field "
            "auto-fills from your plotted route if one exists, or type a system name."
        )
        p2p_note.setWordWrap(True)
        p2p_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        p2p_l.addWidget(p2p_note)

        self._p2p_origin_label = QLabel("Origin: —")
        self._p2p_origin_label.setStyleSheet(_LABEL_STYLE)
        p2p_l.addWidget(self._p2p_origin_label)

        p2p_row = QHBoxLayout()
        p2p_row.setSpacing(8)
        dest_label = QLabel("Destination:")
        dest_label.setStyleSheet(_LABEL_STYLE)
        self._dest_edit = QLineEdit()
        self._dest_edit.setPlaceholderText("System name")
        self._dest_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._dest_edit.textEdited.connect(self._on_dest_edited)
        self._p2p_search_btn = QPushButton("Search")
        self._p2p_search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._p2p_search_btn.clicked.connect(self._start_p2p_search)
        p2p_row.addWidget(dest_label)
        p2p_row.addWidget(self._dest_edit, 1)
        p2p_row.addWidget(self._p2p_search_btn)
        p2p_l.addLayout(p2p_row)

        self._p2p_status_label = QLabel("Dock at a station and enter a destination, then press Search.")
        self._p2p_status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        p2p_l.addWidget(self._p2p_status_label)

        self._p2p_table = QTableWidget()
        self._p2p_table.setColumnCount(9)
        self._p2p_table.setHorizontalHeaderLabels(
            ["Commodity", "Sell Station", "System", "Buy", "Sell", "Profit/u", "Qty", "Total Profit", "Data Age"]
        )
        self._p2p_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._p2p_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p2p_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._p2p_table.verticalHeader().setVisible(False)
        self._p2p_table.setAlternatingRowColors(True)
        self._p2p_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        p2p_h = self._p2p_table.horizontalHeader()
        for c in (0, 1, 2):
            p2p_h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        for c in (3, 4, 5, 6, 7, 8):
            p2p_h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._p2p_table.cellClicked.connect(self._on_p2p_cell_clicked)
        p2p_l.addWidget(self._p2p_table, 1)

        self._p2p_loading_spinner = BusySpinner(self)

        root.addWidget(p2p_frame, 1)
```

- [ ] **Step 5: Extend `refresh()` and add the new methods**

In `edc/ui/panels/trade_route_panel.py`, modify the existing `refresh()` method — find its current body:

```python
    def refresh(self, state) -> None:
        """Cheap, safe to call on every general refresh — just updates the
        location/cargo-capacity display, no search triggered."""
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._cargo_capacity = getattr(state, "cargo_capacity", None)
        self._my_power = getattr(state, "pp_power", None) or None
        self._location_label.setText(f"Location: {self._system or '—'}")
        if isinstance(self._cargo_capacity, int) and self._cargo_capacity > 0:
            self._cargo_label.setText(f"Cargo capacity: {self._cargo_capacity}t (from current ship)")
        else:
            self._cargo_label.setText("Cargo capacity: unknown (fly at least once this session)")
        self._search_btn.setEnabled(bool(self._system) and bool(self._cargo_capacity))
```

Add these lines at the end of that same method (after the existing `self._search_btn.setEnabled(...)` line, still inside `refresh()`):

```python

        self._origin_items = list(getattr(state, "current_market_items", None) or [])
        self._origin_station = (getattr(state, "current_market_station", None) or "").strip()
        self._origin_system = (getattr(state, "current_market_system", None) or "").strip()
        if self._origin_station and self._origin_system:
            self._p2p_origin_label.setText(f"Origin: {self._origin_station} ({self._origin_system})")
        else:
            self._p2p_origin_label.setText("Origin: — (dock and open the Commodities screen first)")

        route_target = (getattr(state, "route_target_system", None) or "").strip()
        if route_target != self._route_target_system:
            self._route_target_system = route_target
            if route_target and not self._dest_user_edited:
                self._dest_edit.setText(route_target)
            elif not route_target and not self._dest_user_edited:
                self._dest_edit.clear()

        self._p2p_search_btn.setEnabled(
            bool(self._origin_items) and bool(self._dest_edit.text().strip())
            and isinstance(self._cargo_capacity, int) and self._cargo_capacity > 0
        )
```

Then add these new methods anywhere in the `TradeRoutePanel` class after the existing `_on_cell_clicked()` method (the last method in the file):

```python
    def _on_dest_edited(self, _text: str) -> None:
        # textEdited only fires on user typing, never on programmatic
        # setText() -- this is what lets the auto-fill know not to
        # clobber something the user typed themselves.
        self._dest_user_edited = True

    def _start_p2p_search(self) -> None:
        destination = self._dest_edit.text().strip()
        if not destination:
            self._p2p_status_label.setText("Enter a destination system first.")
            return
        if not self._origin_items:
            self._p2p_status_label.setText("No origin market data yet — dock and open the Commodities screen.")
            return
        if not isinstance(self._cargo_capacity, int) or self._cargo_capacity <= 0:
            self._p2p_status_label.setText("Cargo capacity unknown yet — undock or check the outfitting screen once.")
            return
        if self._p2p_thread and self._p2p_thread.isRunning():
            return

        self._p2p_search_btn.setEnabled(False)
        self._p2p_status_label.setText(f"Searching for trades to {destination}…")
        self._p2p_table.setRowCount(0)
        self._p2p_loading_spinner.start_over(self)

        self._p2p_worker = _PointToPointWorker(
            self._repo.db.db_path, self._origin_items, destination, self._cargo_capacity,
        )
        self._p2p_thread = QThread()
        self._p2p_worker.moveToThread(self._p2p_thread)
        self._p2p_thread.started.connect(self._p2p_worker.run)
        self._p2p_worker.finished.connect(self._on_p2p_results)
        self._p2p_worker.finished.connect(self._p2p_thread.quit)
        self._p2p_thread.start()

    def _on_p2p_results(self, results: list, error: str) -> None:
        self._p2p_search_btn.setEnabled(
            bool(self._origin_items) and bool(self._dest_edit.text().strip())
            and isinstance(self._cargo_capacity, int) and self._cargo_capacity > 0
        )
        self._p2p_loading_spinner.stop()
        if error:
            self._p2p_status_label.setText(error)
            return
        if not results:
            self._p2p_status_label.setText("No profitable trades found for this destination.")
            self._p2p_table.setRowCount(0)
            return

        self._p2p_status_label.setText(f"Found {len(results)} profitable commodit{'y' if len(results) == 1 else 'ies'}.")
        self._p2p_table.setSortingEnabled(False)
        self._p2p_table.setRowCount(len(results))
        for row, r in enumerate(results):
            commodity_item = QTableWidgetItem(r["commodity"])
            station_item = QTableWidgetItem(r["sell_station_name"])
            system_item = QTableWidgetItem(r["sell_system_name"])
            buy_item = _NumericTableWidgetItem(f"{r['buy_price']:,}", float(r["buy_price"]))
            sell_item = _NumericTableWidgetItem(f"{r['sell_price']:,}", float(r["sell_price"]))
            profit_item = _NumericTableWidgetItem(f"{r['profit_per_unit']:,}", float(r["profit_per_unit"]))
            qty_item = _NumericTableWidgetItem(f"{r['quantity']:,}", float(r["quantity"]))
            total_item = _NumericTableWidgetItem(f"{r['total_profit']:,}", float(r["total_profit"]))
            total_item.setForeground(QColor("#6BCB77"))

            # Same age-bucketing convention as the Loop Planner's own
            # Data Age column in this same file.
            age_hours = r.get("data_age_hours")
            age_text = "—" if age_hours is None else (
                f"{age_hours:.0f}h" if age_hours < 24 else f"{age_hours / 24:.0f}d"
            )
            age_item = _NumericTableWidgetItem(age_text, age_hours if age_hours is not None else -1.0)

            for it in (buy_item, sell_item, profit_item, qty_item, total_item, age_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._p2p_table.setItem(row, 0, commodity_item)
            self._p2p_table.setItem(row, 1, station_item)
            self._p2p_table.setItem(row, 2, system_item)
            self._p2p_table.setItem(row, 3, buy_item)
            self._p2p_table.setItem(row, 4, sell_item)
            self._p2p_table.setItem(row, 5, profit_item)
            self._p2p_table.setItem(row, 6, qty_item)
            self._p2p_table.setItem(row, 7, total_item)
            self._p2p_table.setItem(row, 8, age_item)
        self._p2p_table.setSortingEnabled(True)
        self._p2p_table.sortItems(7, Qt.SortOrder.DescendingOrder)

    def _on_p2p_cell_clicked(self, row: int, column: int) -> None:
        if column not in (1, 2):
            return
        item = self._p2p_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
```

Need `QLineEdit` added to the existing `PyQt6.QtWidgets` import block at the top of the file — change:

```python
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)
```

to:

```python
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)
```

- [ ] **Step 6: Compile-check**

Run: `python -m py_compile edc/ui/panels/trade_route_panel.py`
Expected: no output (success)

- [ ] **Step 7: Run the existing trade_routes tests once more to confirm nothing broke**

Run: `python -m pytest tests/test_trade_routes.py -v`
Expected: PASS (9 passed)

- [ ] **Step 8: Live verification**

Per this project's established convention (`CLAUDE.md`: confirmation means working in-game or visually confirmed in the running app):

1. Launch the app, dock at a station, and open the Commodities screen (populates `state.current_market_items`).
2. Confirm the new "POINT-TO-POINT TRADE FINDER" card shows "Origin: `<station>` (`<system>`)".
3. Type a known nearby system name with market data into the Destination field, click Search.
4. Confirm results appear (or "No profitable trades found" / "No market data for `<system>` yet" if appropriate) and the table is sorted by Total Profit descending.
5. Plot a route to a system via the in-game galaxy map (fires `FSDTarget`) and confirm the Destination field auto-fills with that system's name.
6. Manually edit the Destination field after an auto-fill happened, then plot a *different* route — confirm the field does NOT get overwritten (respects `_dest_user_edited`).

- [ ] **Step 9: Commit**

```bash
git add edc/ui/panels/trade_route_panel.py
git commit -m "feat: add Point-to-Point Trade Finder card to the Trade Route tab"
```
