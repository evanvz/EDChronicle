# EDDN Fleet Carrier Reciprocity (Outbound) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two outbound EDDN gaps — publish the player's own Fleet Carrier's `carrierDockingAccess` on the existing `commodity/3` message, and publish `FCMaterials.json` (currently never sent at all) as a new `fcmaterials_journal/1` message — so other commanders' apps see the same carrier data EDChronicle already consumes from them.

**Architecture:** `edc/core/eddn_publisher.py` gains one new optional parameter on an existing function/method and one new function/method pair mirroring the existing `commodity/3` publish path exactly. `edc/ui/main_window.py` gains one new event-dispatch branch and one new file-reader method, both mirroring existing precedents in the same file.

**Tech Stack:** Python, `requests` (already a dependency, unchanged), pytest (pure-function and queue-inspection tests, no network calls — matches this codebase's existing `tests/test_eddn_commodity.py` pattern exactly).

## Global Constraints

- No new dependency, no new config setting — both new publish paths reuse the existing `AppConfig.eddn_contribute_enabled` opt-in and `_replaying` historical-import guard.
- `fcmaterials_journal/1`'s message schema (verified against EDCD/EDDN's actual repo, not assumed): requires exactly `timestamp`, `event` (literal `"FCMaterials"`), `MarketID`, `CarrierName`, `CarrierID`, `Items[]`, `additionalProperties: false`. Each `Items[]` entry requires exactly `id` (integer, **lowercase** — distinct from the capitalized `Name`/`Price`/`Stock`/`Demand`), `Name`, `Price`, `Stock`, `Demand` — no `Category`, `Category_Localised`, `Name_Localised`, or any other key.
- `carrierDockingAccess` is only ever populated for the player's own, confirmed-owned carrier (`state.carrier_owned_market_id`) — never for a third-party carrier, since the app has no way to know another commander's carrier access.
- Spec of record: `docs/superpowers/specs/2026-08-16-eddn-carrier-reciprocity-design.md`.

---

### Task 1: `eddn_publisher.py` — docking access field + FCMaterials publish

**Files:**
- Modify: `edc/core/eddn_publisher.py`
- Modify: `tests/test_eddn_commodity.py` (new tests for the `docking_access` parameter)
- Test: `tests/test_eddn_fcmaterials_publish.py` (new — outbound publish tests; distinct from the existing `tests/test_eddn_fcmaterials.py`, which tests the *inbound* listener-side buffer, a different module)

**Interfaces:**
- Produces: `build_commodity_message(data: Dict[str, Any], docking_access: Optional[str] = None) -> Optional[Dict[str, Any]]` — unchanged behavior when `docking_access` is omitted/`None`; when given a non-empty string, the returned message gains `"carrierDockingAccess": docking_access`.
- Produces: `EddnPublisher.maybe_publish_commodity(self, data: Dict[str, Any], docking_access: Optional[str] = None) -> None` — same new optional parameter, threaded straight to `build_commodity_message`.
- Produces: `build_fcmaterials_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]` — returns `None` if `MarketID`/`CarrierName`/`CarrierID`/`timestamp`/`Items` are missing/malformed, or no valid items remain after filtering; otherwise returns the schema-compliant message dict.
- Produces: `EddnPublisher.maybe_publish_fcmaterials(self, data: Dict[str, Any]) -> None` — same guard/queue pattern as `maybe_publish_commodity`.
- Produces: module-level `_FCMATERIALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"`.

This task's four new/changed interfaces are consumed by Task 2 (`main_window.py`'s call sites).

- [ ] **Step 1: Write the failing tests**

Re-read `tests/test_eddn_commodity.py` fresh (shown above in full at plan-writing time — confirm current line numbers before editing), then add these tests at the end of that file:

```python
def test_docking_access_added_when_provided():
    msg = build_commodity_message(_market([_item()]), docking_access="all")
    assert msg["carrierDockingAccess"] == "all"


def test_docking_access_absent_when_not_provided():
    msg = build_commodity_message(_market([_item()]))
    assert "carrierDockingAccess" not in msg


def test_docking_access_absent_when_empty_string():
    msg = build_commodity_message(_market([_item()]), docking_access="")
    assert "carrierDockingAccess" not in msg


def test_maybe_publish_commodity_threads_docking_access_into_queued_message():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]), docking_access="friends")

    payload = pub._queue.get_nowait()
    assert payload["message"]["carrierDockingAccess"] == "friends"


def test_maybe_publish_commodity_omits_docking_access_key_when_not_given():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000"})

    pub.maybe_publish_commodity(_market([_item()]))

    payload = pub._queue.get_nowait()
    assert "carrierDockingAccess" not in payload["message"]
```

Create `tests/test_eddn_fcmaterials_publish.py`:

```python
"""Tests for build_fcmaterials_message() and
EddnPublisher.maybe_publish_fcmaterials() -- transforms an FCMaterials.json
dict into an EDDN fcmaterials_journal/1-compliant message body. Schema
requirements (exact required fields, lowercase "id", additionalProperties:
false) verified directly against EDCD/EDDN's schema repo -- see
docs/superpowers/specs/2026-08-16-eddn-carrier-reciprocity-design.md."""
from edc.core.eddn_publisher import (
    build_fcmaterials_message, EddnPublisher, _FCMATERIALS_SCHEMA_REF,
)


def _fcmaterials(items):
    return {
        "timestamp": "2026-08-16T10:00:00Z",
        "event": "FCMaterials",
        "MarketID": 3705599744,
        "CarrierID": "K7X-83Z",
        "CarrierName": "TESTBED",
        "Items": items,
    }


def _fc_item(name="$graphene_name;", **overrides):
    it = {
        "id": 128924331,
        "Name": name,
        "Name_Localised": "Graphene",
        "Category": "$MARKET_category_manufactured;",
        "Category_Localised": "Manufactured",
        "Price": 1200,
        "Stock": 50,
        "Demand": 0,
    }
    it.update(overrides)
    return it


def test_valid_fcmaterials_produces_compliant_message():
    msg = build_fcmaterials_message(_fcmaterials([_fc_item()]))
    assert msg == {
        "timestamp": "2026-08-16T10:00:00Z",
        "event": "FCMaterials",
        "MarketID": 3705599744,
        "CarrierID": "K7X-83Z",
        "CarrierName": "TESTBED",
        "Items": [{
            "id": 128924331,
            "Name": "$graphene_name;",
            "Price": 1200,
            "Stock": 50,
            "Demand": 0,
        }],
    }


def test_name_localised_and_category_dropped_from_item():
    msg = build_fcmaterials_message(_fcmaterials([_fc_item()]))
    item = msg["Items"][0]
    for forbidden_key in ("Name_Localised", "Category", "Category_Localised"):
        assert forbidden_key not in item


def test_missing_market_id_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["MarketID"]
    assert build_fcmaterials_message(data) is None


def test_missing_carrier_name_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["CarrierName"]
    assert build_fcmaterials_message(data) is None


def test_missing_carrier_id_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["CarrierID"]
    assert build_fcmaterials_message(data) is None


def test_missing_timestamp_returns_none():
    data = _fcmaterials([_fc_item()])
    del data["timestamp"]
    assert build_fcmaterials_message(data) is None


def test_not_a_dict_returns_none():
    assert build_fcmaterials_message(None) is None
    assert build_fcmaterials_message([]) is None


def test_empty_items_returns_none():
    assert build_fcmaterials_message(_fcmaterials([])) is None


def test_item_missing_id_is_dropped_but_others_survive():
    bad = _fc_item(name="$landmines_name;")
    del bad["id"]
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_item_with_non_int_price_is_dropped_but_others_survive():
    bad = _fc_item(name="$landmines_name;", Price="not a number")
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_item_with_bool_price_is_dropped():
    bad = _fc_item(name="$landmines_name;", Price=True)
    msg = build_fcmaterials_message(_fcmaterials([_fc_item(), bad]))
    names = [i["Name"] for i in msg["Items"]]
    assert names == ["$graphene_name;"]


def test_all_items_invalid_returns_none():
    bad = _fc_item()
    del bad["id"]
    assert build_fcmaterials_message(_fcmaterials([bad])) is None


def test_maybe_publish_fcmaterials_queues_compliant_envelope():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({
        "event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000",
        "Horizons": False, "Odyssey": True,
    })

    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))

    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == _FCMATERIALS_SCHEMA_REF
    assert payload["header"]["uploaderID"] == "CMDR Test"
    assert payload["header"]["softwareName"] == "EDChronicle"
    assert payload["message"]["CarrierName"] == "TESTBED"
    assert payload["message"]["Items"][0]["Name"] == "$graphene_name;"
    assert payload["message"]["horizons"] is False
    assert payload["message"]["odyssey"] is True


def test_maybe_publish_fcmaterials_skips_when_no_commander_known():
    pub = EddnPublisher()
    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))
    assert pub._queue.empty()


def test_maybe_publish_fcmaterials_skips_invalid_data():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.maybe_publish_fcmaterials({"not": "valid fcmaterials"})
    assert pub._queue.empty()


def test_maybe_publish_fcmaterials_skips_beta_build():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0 beta 1", "build": "r300000"})

    pub.maybe_publish_fcmaterials(_fcmaterials([_fc_item()]))

    assert pub._queue.empty()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_eddn_commodity.py tests/test_eddn_fcmaterials_publish.py -v`
Expected: the new `docking_access` tests FAIL with `TypeError: build_commodity_message() got an unexpected keyword argument 'docking_access'` (or similar); the new file FAILS at collection with `ImportError: cannot import name 'build_fcmaterials_message'` (and `_FCMATERIALS_SCHEMA_REF`).

- [ ] **Step 3: Add `docking_access` to `build_commodity_message` and `maybe_publish_commodity`**

Re-read `edc/core/eddn_publisher.py` fresh, then change `build_commodity_message`'s signature (currently `def build_commodity_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:`) to:

```python
def build_commodity_message(data: Dict[str, Any], docking_access: Optional[str] = None) -> Optional[Dict[str, Any]]:
```

and change its final `return { ... }` block (currently):

```python
    return {
        "systemName": system_name,
        "stationName": station_name,
        "marketId": market_id,
        "timestamp": timestamp,
        "commodities": commodities,
    }
```

to:

```python
    msg = {
        "systemName": system_name,
        "stationName": station_name,
        "marketId": market_id,
        "timestamp": timestamp,
        "commodities": commodities,
    }
    if isinstance(docking_access, str) and docking_access:
        msg["carrierDockingAccess"] = docking_access
    return msg
```

Change `EddnPublisher.maybe_publish_commodity`'s signature (currently `def maybe_publish_commodity(self, data: Dict[str, Any]) -> None:`) to:

```python
    def maybe_publish_commodity(self, data: Dict[str, Any], docking_access: Optional[str] = None) -> None:
```

and its `msg = build_commodity_message(data)` line to:

```python
        msg = build_commodity_message(data, docking_access)
```

- [ ] **Step 4: Add the `fcmaterials_journal/1` schema constant**

In the same file, add this line immediately after the existing `_COMMODITY_SCHEMA_REF = "https://eddn.edcd.io/schemas/commodity/3"` line:

```python
_FCMATERIALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"
```

- [ ] **Step 5: Add `build_fcmaterials_message`**

Add this new function immediately after `build_commodity_message` (before the `class EddnPublisher:` line):

```python
def build_fcmaterials_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Returns an fcmaterials_journal/1-schema-compliant "message" body built
    from an FCMaterials.json dict, or None if required fields are missing
    or no valid items remain. Schema requires exactly timestamp, event
    ("FCMaterials"), MarketID, CarrierName, CarrierID, Items[] at the top
    level (additionalProperties: false), and exactly id (int, lowercase),
    Name, Price, Stock, Demand per item -- verified directly against
    EDCD/EDDN's schema repo, not assumed.
    """
    if not isinstance(data, dict):
        return None

    market_id = data.get("MarketID")
    carrier_name = data.get("CarrierName")
    carrier_id = data.get("CarrierID")
    timestamp = data.get("timestamp")
    items = data.get("Items")

    if not (
        isinstance(market_id, int)
        and isinstance(carrier_name, str) and carrier_name
        and isinstance(carrier_id, str) and carrier_id
        and isinstance(timestamp, str) and timestamp
        and isinstance(items, list)
    ):
        return None

    out_items: list = []
    dropped_invalid = 0
    for it in items:
        if not isinstance(it, dict):
            dropped_invalid += 1
            continue
        item_id = it.get("id")
        name = it.get("Name")
        price = it.get("Price")
        stock = it.get("Stock")
        demand = it.get("Demand")
        if not (
            isinstance(item_id, int) and not isinstance(item_id, bool)
            and isinstance(name, str) and name
            and isinstance(price, int) and not isinstance(price, bool)
            and isinstance(stock, int) and not isinstance(stock, bool)
            and isinstance(demand, int) and not isinstance(demand, bool)
        ):
            dropped_invalid += 1
            continue
        out_items.append({
            "id": item_id,
            "Name": name,
            "Price": price,
            "Stock": stock,
            "Demand": demand,
        })

    if dropped_invalid:
        log.warning(
            "EDDN fcmaterials message for %r/%r dropped %d malformed item(s)",
            carrier_name, market_id, dropped_invalid,
        )

    if not out_items:
        return None

    return {
        "timestamp": timestamp,
        "event": "FCMaterials",
        "MarketID": market_id,
        "CarrierName": carrier_name,
        "CarrierID": carrier_id,
        "Items": out_items,
    }
```

- [ ] **Step 6: Add `EddnPublisher.maybe_publish_fcmaterials`**

Add this new method immediately after `maybe_publish_commodity` (before `def _worker_loop`):

```python
    def maybe_publish_fcmaterials(self, data: Dict[str, Any]) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_fcmaterials_message(data)
        if msg is None:
            return

        msg["horizons"] = self._horizons
        msg["odyssey"] = self._odyssey

        payload = {
            "$schemaRef": _FCMATERIALS_SCHEMA_REF,
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
            log.warning("EDDN publish queue full — dropping fcmaterials message")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_eddn_commodity.py tests/test_eddn_fcmaterials_publish.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add edc/core/eddn_publisher.py tests/test_eddn_commodity.py tests/test_eddn_fcmaterials_publish.py
git commit -m "feat: publish carrierDockingAccess and FCMaterials.json to EDDN"
```

---

### Task 2: `main_window.py` — wire both publish paths

**Files:**
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `EddnPublisher.maybe_publish_commodity(self, data, docking_access=None)` and `EddnPublisher.maybe_publish_fcmaterials(self, data)` (Task 1).
- Produces: `MainWindow._load_current_fcmaterials(self) -> Optional[dict]` — no other task depends on this; it's this plan's terminal interface.

This task has no automated test — this pipeline (journal-event-triggered EDDN publishing) has no test coverage anywhere in `main_window.py` today, matching this codebase's established convention. Verification is a static syntax check, the full test suite, and a manual smoke check of `build_fcmaterials_message()` end to end (Task 1's function, exercised here with a file-shaped dict to confirm the reader's output would actually satisfy it). A live in-app/in-game check — confirming both events actually fire when docked at the player's own carrier — is out of scope for this task's implementer (no interactive game session) and is noted as pending for a human at the end.

- [ ] **Step 1: Re-read `main_window.py` fresh**

Re-read `edc/ui/main_window.py` around lines 650-680 (`_load_current_market`) and lines 2095-2115 (the `"Market"` event handler) fresh — this file is on the project's frequently-stale list, confirm current line numbers before editing.

- [ ] **Step 2: Add `_load_current_fcmaterials`**

Add this new method immediately after `_load_current_market` (currently ends around line 677 with `return None` inside its `except` block, followed by whatever comes next — place this new method right after that method's closing, before the next method definition):

```python
    def _load_current_fcmaterials(self):
        """
        Reads FCMaterials.json (written by the game alongside the journal
        whenever the carrier's Commodities Market screen is opened) --
        mirrors _load_current_market()'s Market.json reading exactly, for
        the same reason: EDDN publishing needs the raw dict shape, not a
        UI-shaped subset.
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return None
        fc_path = Path(journal_dir) / "FCMaterials.json"
        try:
            if not fc_path.exists():
                return None
            data = json.loads(fc_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read FCMaterials.json")
            return None
        return data
```

(This mirrors `_load_current_market`'s exact structure — same `journal_dir` lookup, same `Path`/`json.loads`/try-except pattern, `Path` and `json` are already imported at the top of this file since `_load_current_market` already uses them.)

- [ ] **Step 3: Update the `"Market"` handler to pass `docking_access`**

Change the current block:

```python
        if name == "Market":
            market_data = self._load_current_market()
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)
            self.market_panel.refresh_commodity_names()
            self.mining_panel.refresh_commodity_names()
            if market_data and getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
                self.eddn_publisher.maybe_publish_commodity(market_data)
```

to:

```python
        if name == "Market":
            market_data = self._load_current_market()
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)
            self.market_panel.refresh_commodity_names()
            self.mining_panel.refresh_commodity_names()
            if market_data and getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
                docking_access = None
                if market_data.get("MarketID") == getattr(self.state, "carrier_owned_market_id", None):
                    docking_access = getattr(self.state, "carrier_docking_access", None)
                self.eddn_publisher.maybe_publish_commodity(market_data, docking_access)
```

- [ ] **Step 4: Add the `"FCMaterials"` event branch**

In the same event-dispatch method, immediately after the `"Market"` block from Step 3, add:

```python
        if name == "FCMaterials":
            fc_data = self._load_current_fcmaterials()
            if fc_data and getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
                self.eddn_publisher.maybe_publish_fcmaterials(fc_data)
```

- [ ] **Step 5: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS — no regression.

- [ ] **Step 7: Manual smoke check — reader output satisfies the builder**

Run this to confirm a realistic `FCMaterials.json`-shaped dict (as `_load_current_fcmaterials` would return it) actually produces a valid message through Task 1's `build_fcmaterials_message`:

```
.venv/Scripts/python.exe -c "
from edc.core.eddn_publisher import build_fcmaterials_message

sample = {
    'timestamp': '2026-08-16T12:00:00Z', 'event': 'FCMaterials',
    'MarketID': 3705599744, 'CarrierID': 'K7X-83Z', 'CarrierName': 'TESTBED',
    'Items': [
        {'id': 128924331, 'Name': '\$graphene_name;', 'Name_Localised': 'Graphene',
         'Category': '\$MARKET_category_manufactured;', 'Category_Localised': 'Manufactured',
         'Price': 1200, 'Stock': 50, 'Demand': 0},
    ],
}
msg = build_fcmaterials_message(sample)
assert msg is not None, 'expected a valid message'
assert msg['Items'][0]['Name'] == '\$graphene_name;'
assert 'Name_Localised' not in msg['Items'][0]
print('OK: FCMaterials.json-shaped dict produces a valid fcmaterials_journal/1 message')
"
```

Expected output: `OK: FCMaterials.json-shaped dict produces a valid fcmaterials_journal/1 message`

- [ ] **Step 8: Note pending live verification**

This task's actual runtime correctness (does opening the carrier's Commodities Market screen in-game really fire an `FCMaterials` event with `_load_current_fcmaterials()` reading real data, and does docking at your own carrier's market really populate `carrierDockingAccess` on the queued commodity message) can only be confirmed by a human with a live game session and `eddn_contribute_enabled` turned on — record this as pending, do not claim it as verified.

- [ ] **Step 9: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: wire FCMaterials publishing and carrier docking access into the Market/FCMaterials event handlers"
```
