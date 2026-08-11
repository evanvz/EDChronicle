# EDDN Commodity Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the player's own market visits (`Market.json`) to EDDN's `commodity/3` schema, reusing the existing `EddnPublisher` queue/worker/retry infrastructure that currently only publishes `journal/1` events.

**Architecture:** A new pure function `build_commodity_message()` transforms a `Market.json`-shaped dict into an EDDN-compliant `commodity/3` message body. A new `EddnPublisher.maybe_publish_commodity()` method wraps it with the same header/gating logic `maybe_publish()` already uses and pushes onto the same `self._queue` — no new thread, no new queue, no new setting. `main_window.py`'s existing `"Market"` event branch reads `Market.json` a second time (matching this file's existing pattern — `_seed_commodity_names_from_market_json()` and `_load_current_market()` already each independently re-read it) and calls the new method.

**Tech Stack:** Python 3.14, PyQt6, `requests` (already used by `EddnPublisher`), `pytest`.

## Global Constraints

- Reuse `eddn_contribute_enabled` config flag — no new setting, no new UI toggle (spec decision, confirmed with user).
- Must skip during journal bootstrap replay — matches the exact guard already used for `maybe_publish()` at `edc/ui/main_window.py:1832` (`not self._replaying`), otherwise every app restart would re-publish stale `Market.json` data as if it just happened.
- Must skip beta builds — matches `maybe_publish()`'s existing `if self._is_beta: return` (`edc/core/eddn_publisher.py:183-184`).
- Elisions required by EDDN's `commodity-README.md` (verified against a real `Market.json` on disk): drop `StationType` at message level; drop `Producer`, `Rare`, `id`, `Category`/`Category_Localised` from each item; strip `$…_name;` wrapper from `Name`; skip the Limpets/Drones commodity (the only `NonMarketable`-category commodity in EDCD's `FDevIDs/commodity.csv` — internal symbol `drones`); omit `economies`/`prohibited` entirely (never send empty lists for them).
- Required per-commodity fields per `commodity-v3.0.json`: `name`, `meanPrice`, `buyPrice`, `stock`, `stockBracket`, `sellPrice`, `demand`, `demandBracket` — all confirmed present in real `Market.json` item data under their journal names (`Name`, `MeanPrice`, `BuyPrice`, `Stock`, `StockBracket`, `SellPrice`, `Demand`, `DemandBracket`).

---

### Task 1: `build_commodity_message()` pure function

**Files:**
- Modify: `edc/core/eddn_publisher.py`
- Test: `tests/test_eddn_commodity.py`

**Interfaces:**
- Produces: `build_commodity_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]` — takes a `Market.json`-shaped dict, returns a `commodity/3` `"message"` body (not the full envelope — no `$schemaRef`/`header`), or `None` if required fields are missing or zero tradeable commodities remain.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eddn_commodity.py`:

```python
"""Tests for build_commodity_message() -- transforms a Market.json dict
into an EDDN commodity/3-compliant message body. Elision/rename rules
verified against EDDN's own commodity-README.md and a real Market.json
sample (see docs/superpowers/specs/2026-08-11-eddn-commodity-publish-design.md)."""
from edc.core.eddn_publisher import build_commodity_message


def _market(items):
    return {
        "timestamp": "2026-08-11T10:00:00Z",
        "event": "Market",
        "MarketID": 128049152,
        "StationName": "Jameson Memorial",
        "StationType": "Orbis",
        "StarSystem": "Shinrarta Dezhra",
        "Items": items,
    }


def _item(name="$platinum_name;", **overrides):
    it = {
        "id": 128049152,
        "Name": name,
        "Name_Localised": "Platinum",
        "Category": "$MARKET_category_metals;",
        "Category_Localised": "Metals",
        "BuyPrice": 0,
        "SellPrice": 59006,
        "MeanPrice": 55505,
        "StockBracket": 0,
        "DemandBracket": 3,
        "Stock": 0,
        "Demand": 33966,
        "Consumer": True,
        "Producer": False,
        "Rare": False,
    }
    it.update(overrides)
    return it


def test_valid_market_produces_compliant_message():
    msg = build_commodity_message(_market([_item()]))
    assert msg == {
        "systemName": "Shinrarta Dezhra",
        "stationName": "Jameson Memorial",
        "marketId": 128049152,
        "timestamp": "2026-08-11T10:00:00Z",
        "commodities": [{
            "name": "platinum",
            "meanPrice": 55505,
            "buyPrice": 0,
            "stock": 0,
            "stockBracket": 0,
            "sellPrice": 59006,
            "demand": 33966,
            "demandBracket": 3,
        }],
    }


def test_name_dollar_wrapper_is_stripped():
    msg = build_commodity_message(_market([_item(name="$aluminium_name;")]))
    assert msg["commodities"][0]["name"] == "aluminium"


def test_limpets_are_skipped():
    limpets = _item(
        name="$drones_name;",
        Category="$MARKET_category_nonmarketable;",
        Category_Localised="Non-marketable",
    )
    msg = build_commodity_message(_market([_item(), limpets]))
    names = [c["name"] for c in msg["commodities"]]
    assert "drones" not in names
    assert names == ["platinum"]


def test_producer_rare_id_category_are_dropped_from_item():
    msg = build_commodity_message(_market([_item()]))
    commodity = msg["commodities"][0]
    for forbidden_key in ("Producer", "Rare", "id", "Category", "Category_Localised"):
        assert forbidden_key not in commodity


def test_station_type_is_dropped_from_message():
    msg = build_commodity_message(_market([_item()]))
    assert "StationType" not in msg
    assert "stationType" not in msg


def test_economies_and_prohibited_are_never_present():
    msg = build_commodity_message(_market([_item()]))
    assert "economies" not in msg
    assert "prohibited" not in msg


def test_missing_required_field_returns_none():
    data = _market([_item()])
    del data["MarketID"]
    assert build_commodity_message(data) is None


def test_no_tradeable_commodities_returns_none():
    limpets = _item(name="$drones_name;", Category="$MARKET_category_nonmarketable;")
    assert build_commodity_message(_market([limpets])) is None


def test_not_a_dict_returns_none():
    assert build_commodity_message(None) is None
    assert build_commodity_message([]) is None


def test_empty_items_returns_none():
    assert build_commodity_message(_market([])) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_eddn_commodity.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_commodity_message'`

- [ ] **Step 3: Implement `build_commodity_message()`**

Add to `edc/core/eddn_publisher.py`, after the existing `_FACTION_DISALLOWED` constant (around line 36):

```python
_COMMODITY_SCHEMA_REF = "https://eddn.edcd.io/schemas/commodity/3"

# The only commodity FDevIDs' commodity.csv lists under category
# "NonMarketable" -- Limpets are always available at a fixed price
# regardless of station economy, so EDDN's own commodity-README.md says
# to skip them rather than report them as a normal traded good.
_NONMARKETABLE_SYMBOL = "drones"


def _commodity_symbol(raw_name: str) -> str:
    """Strip the '$...name;' wrapper Market.json uses for internal
    commodity names, e.g. '$platinum_name;' -> 'platinum'."""
    s = raw_name
    if s.startswith("$"):
        s = s[1:]
    if s.endswith("_name;"):
        s = s[: -len("_name;")]
    return s


def build_commodity_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Returns a commodity/3-schema-compliant "message" body built from a
    Market.json dict, or None if required fields are missing or no
    tradeable commodities remain after the Limpets skip rule.
    """
    if not isinstance(data, dict):
        return None

    system_name = data.get("StarSystem")
    station_name = data.get("StationName")
    market_id = data.get("MarketID")
    timestamp = data.get("timestamp")
    items = data.get("Items")

    if not (
        isinstance(system_name, str) and system_name
        and isinstance(station_name, str) and station_name
        and isinstance(market_id, int)
        and isinstance(timestamp, str) and timestamp
        and isinstance(items, list)
    ):
        return None

    commodities: list = []
    for it in items:
        if not isinstance(it, dict):
            continue
        raw_name = it.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        symbol = _commodity_symbol(raw_name)
        if not symbol or symbol == _NONMARKETABLE_SYMBOL:
            continue

        mean_price = it.get("MeanPrice")
        buy_price = it.get("BuyPrice")
        stock = it.get("Stock")
        stock_bracket = it.get("StockBracket")
        sell_price = it.get("SellPrice")
        demand = it.get("Demand")
        demand_bracket = it.get("DemandBracket")
        if not all(isinstance(v, int) for v in (mean_price, buy_price, stock, sell_price, demand)):
            continue
        if stock_bracket not in (0, 1, 2, 3, ""):
            continue
        if demand_bracket not in (0, 1, 2, 3, ""):
            continue

        commodities.append({
            "name": symbol,
            "meanPrice": mean_price,
            "buyPrice": buy_price,
            "stock": stock,
            "stockBracket": stock_bracket,
            "sellPrice": sell_price,
            "demand": demand,
            "demandBracket": demand_bracket,
        })

    if not commodities:
        return None

    return {
        "systemName": system_name,
        "stationName": station_name,
        "marketId": market_id,
        "timestamp": timestamp,
        "commodities": commodities,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_eddn_commodity.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add edc/core/eddn_publisher.py tests/test_eddn_commodity.py
git commit -m "feat: build EDDN commodity/3 messages from Market.json"
```

---

### Task 2: `EddnPublisher.maybe_publish_commodity()`

**Files:**
- Modify: `edc/core/eddn_publisher.py`
- Test: `tests/test_eddn_commodity.py`

**Interfaces:**
- Consumes: `build_commodity_message(data)` from Task 1; `EddnPublisher._is_beta`, `self._commander`, `self._queue` (all already exist in the class).
- Produces: `EddnPublisher.maybe_publish_commodity(data: Dict[str, Any]) -> None` — same shape as the existing `maybe_publish()`.

- [ ] **Step 1: Write the failing test**

First, update the existing top-of-file import in `tests/test_eddn_commodity.py`
from:

```python
from edc.core.eddn_publisher import build_commodity_message
```

to:

```python
from edc.core.eddn_publisher import build_commodity_message, EddnPublisher, _COMMODITY_SCHEMA_REF
```

Then append these tests to the end of the same file:

```python
def test_maybe_publish_commodity_queues_compliant_envelope():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]))

    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == _COMMODITY_SCHEMA_REF
    assert payload["header"]["uploaderID"] == "CMDR Test"
    assert payload["header"]["softwareName"] == "EDChronicle"
    assert payload["header"]["gameversion"] == "4.0"
    assert payload["message"]["systemName"] == "Shinrarta Dezhra"
    assert payload["message"]["commodities"][0]["name"] == "platinum"


def test_maybe_publish_commodity_skips_when_no_commander_known():
    pub = EddnPublisher()
    pub.maybe_publish_commodity(_market([_item()]))
    assert pub._queue.empty()


def test_maybe_publish_commodity_skips_invalid_market_data():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.maybe_publish_commodity({"not": "a valid market"})
    assert pub._queue.empty()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_eddn_commodity.py -v`
Expected: FAIL with `AttributeError: 'EddnPublisher' object has no attribute 'maybe_publish_commodity'`

- [ ] **Step 3: Implement `maybe_publish_commodity()`**

Add to the `EddnPublisher` class in `edc/core/eddn_publisher.py`, directly after the existing `maybe_publish()` method:

```python
    def maybe_publish_commodity(self, data: Dict[str, Any]) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_commodity_message(data)
        if msg is None:
            return

        payload = {
            "$schemaRef": _COMMODITY_SCHEMA_REF,
            "header": {
                "uploaderID": self._commander,
                "softwareName": _SOFTWARE_NAME,
                "softwareVersion": _SOFTWARE_VERSION,
                "gameversion": self._gameversion,
                "gamebuild": self._gamebuild,
            },
            "message": msg,
        }
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            log.warning("EDDN publish queue full — dropping commodity message")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_eddn_commodity.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add edc/core/eddn_publisher.py tests/test_eddn_commodity.py
git commit -m "feat: EddnPublisher.maybe_publish_commodity queues commodity/3 payloads"
```

---

### Task 3: Wire into the `"Market"` journal event handler

**Files:**
- Modify: `edc/ui/main_window.py:1867-1872`

**Interfaces:**
- Consumes: `self.eddn_publisher.maybe_publish_commodity(data)` from Task 2; `self.cfg.eddn_contribute_enabled`, `self._replaying`, `self.cfg.journal_dir` (all already exist on `MainWindow`).

- [ ] **Step 1: Add the publish call to the existing `"Market"` branch**

In `edc/ui/main_window.py`, the `"Market"` event branch currently reads (lines 1867-1872):

```python
        if name == "Market":
            self._load_current_market()
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)
            self.market_panel.refresh_commodity_names()
            self.mining_panel.refresh_commodity_names()
```

Change it to:

```python
        if name == "Market":
            self._load_current_market()
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)
            self.market_panel.refresh_commodity_names()
            self.mining_panel.refresh_commodity_names()
            if getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
                self._publish_market_to_eddn()
```

Add the new method near `_load_current_market()` (after it, around line 641):

```python
    def _publish_market_to_eddn(self) -> None:
        """
        Independent Market.json read for EDDN publishing, same pattern as
        _load_current_market() and _seed_commodity_names_from_market_json()
        each doing their own read -- keeps this decoupled from the
        UI-shaped state.current_market_items (which drops fields EDDN
        requires, like MeanPrice/StockBracket/DemandBracket).
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        market_path = Path(journal_dir) / "Market.json"
        try:
            if not market_path.exists():
                return
            data = json.loads(market_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read Market.json for EDDN publish")
            return
        self.eddn_publisher.maybe_publish_commodity(data)
```

- [ ] **Step 2: Compile-check**

Run: `python -m py_compile edc/ui/main_window.py`
Expected: no output (success)

- [ ] **Step 3: Live verification**

Per project rules (`CLAUDE.md`: confirmation means working in-game or visually confirmed in the running app), this task's actual correctness can only be confirmed live — Task 1's tests already prove the message-building logic is correct in isolation:

1. Launch the app with `eddn_contribute_enabled: true` (already the default).
2. In-game, dock at any station and open the Commodities Market screen (fires the `Market` journal event).
3. Check the newest `logs/edc_*.log` — should show no new `ERROR` lines from `eddn_publisher`/`main_window` around that timestamp.
4. Confirm no `403`/non-200 warnings logged from `_send_with_retry` (`log.warning("EDDN gateway rejected message...")`).
5. Optional: cross-check the station's prices appear/refresh on EDDN's own site (`edsm.net`-adjacent — actually `eddn.edcd.io` has no public browse UI; Inara or EDSM's own station pages will reflect it within a few minutes if desired, but absence of errors in the log is sufficient confirmation the message was accepted).

- [ ] **Step 4: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: publish market visits to EDDN commodity/3 on Market event"
```
