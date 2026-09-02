"""EDDN publisher — contributes data back to the shared Elite Dangerous
Data Network, the same feed Spansh/EDSM/Inara consume from. Two schemas:

- journal/1 — Docked, FSDJump, Scan, Location, SAASignalsFound,
  CarrierJump, CodexEntry events. Everything else is silently skipped
  (not an error — most journal events simply aren't part of this schema).
  Reference: https://github.com/EDCD/EDDN/blob/live/schemas/journal-v1.0.json
- commodity/3 — the player's own market visits (Market.json), built via
  build_commodity_message(). Reference:
  https://github.com/EDCD/EDDN/blob/live/schemas/commodity-v3.0.json

Opt-in only (AppConfig.eddn_contribute_enabled). The actual HTTP POST runs
on a background worker thread via a shared queue, so journal-event
processing on the UI thread is never blocked by network I/O.
"""
from __future__ import annotations

import copy
import logging
import queue
import threading
from typing import Any, Dict, Optional, Sequence

import requests

log = logging.getLogger(__name__)

_GATEWAY_URL = "https://eddn.edcd.io:4430/upload/"
_SCHEMA_REF = "https://eddn.edcd.io/schemas/journal/1"
_COMMODITY_SCHEMA_REF = "https://eddn.edcd.io/schemas/commodity/3"
_FCMATERIALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"
_FSSBODYSIGNALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fssbodysignals/1"

_ALLOWED_EVENTS = {"Docked", "FSDJump", "Scan", "Location", "SAASignalsFound", "CarrierJump", "CodexEntry"}

_TOP_LEVEL_DISALLOWED = {
    "ActiveFine", "CockpitBreach", "BoostUsed", "FuelLevel", "FuelUsed",
    "JumpDist", "Latitude", "Longitude", "Wanted", "IsNewEntry",
    "NewTraitsDiscovered", "Traits", "VoucherAmount",
}
_FACTION_DISALLOWED = {"HappiestSystem", "HomeSystem", "MyReputation", "SquadronFaction"}

# The only commodity FDevIDs' commodity.csv lists under category
# "NonMarketable" -- Limpets are always available at a fixed price
# regardless of station economy, so EDDN's own commodity-README.md says
# to skip them rather than report them as a normal traded good. Checked
# both by symbol (the one confirmed real case) and by category substring
# (in case FDev ever adds a second NonMarketable commodity) so neither
# check alone has to be exactly right.
_NONMARKETABLE_SYMBOL = "drones"

_SOFTWARE_NAME = "EDChronicle"
_SOFTWARE_VERSION = "1.0.0"

_RETRY_DELAY_SECONDS = 60
_RETRY_MAX_ATTEMPTS = 5  # a poisoned message must not cycle the queue forever
_QUEUE_MAX = 200
_POST_TIMEOUT = 15


def _strip_localised(obj: Any) -> Any:
    """Recursively drop any dict key ending in '_Localised' — required by EDDN."""
    if isinstance(obj, dict):
        return {
            k: _strip_localised(v)
            for k, v in obj.items()
            if not (isinstance(k, str) and k.endswith("_Localised"))
        }
    if isinstance(obj, list):
        return [_strip_localised(v) for v in obj]
    return obj


def _commodity_symbol(raw_name: str) -> str:
    """Strip the '$...name;' wrapper Market.json uses for internal
    commodity names, e.g. '$platinum_name;' -> 'platinum'."""
    s = raw_name
    if s.startswith("$"):
        s = s[1:]
    if s.endswith("_name;"):
        s = s[: -len("_name;")]
    return s


def build_message(
    event: Dict[str, Any],
    star_system: str,
    star_pos: Optional[Sequence[float]],
    system_address: Optional[int],
) -> Optional[Dict[str, Any]]:
    """
    Returns a journal/1-schema-compliant message body, or None if this
    event isn't covered by the schema or lacks enough context to complete
    the required StarSystem/StarPos/SystemAddress fields.
    """
    name = event.get("event")
    if name not in _ALLOWED_EVENTS:
        return None

    msg = _strip_localised(copy.deepcopy(event))

    for key in _TOP_LEVEL_DISALLOWED:
        msg.pop(key, None)

    factions = msg.get("Factions")
    if isinstance(factions, list):
        for f in factions:
            if isinstance(f, dict):
                for key in _FACTION_DISALLOWED:
                    f.pop(key, None)

    if not msg.get("StarSystem"):
        if not star_system:
            return None
        msg["StarSystem"] = star_system

    if not msg.get("StarPos"):
        if not (isinstance(star_pos, (list, tuple)) and len(star_pos) == 3):
            return None
        msg["StarPos"] = list(star_pos)

    if not isinstance(msg.get("SystemAddress"), int):
        if not isinstance(system_address, int):
            return None
        msg["SystemAddress"] = system_address

    return msg


def build_fssbodysignals_message(
    event: Dict[str, Any],
    star_system: str,
    star_pos: Optional[Sequence[float]],
    system_address: Optional[int],
) -> Optional[Dict[str, Any]]:
    """
    Returns an fssbodysignals/1-schema-compliant message body for an
    FSSBodySignals event, or None if required fields are missing. Schema
    requires exactly timestamp, event, StarSystem, StarPos, SystemAddress,
    BodyID, Signals[] (each Signal: Type, Count only) at message level
    (additionalProperties: false) -- verified directly against EDCD/EDDN's
    schema repo. This is the schema that carries Surface Mining's
    "$PlanetaryMiningLocation_Name;" signal to the wider community.
    """
    if event.get("event") != "FSSBodySignals":
        return None

    timestamp = event.get("timestamp")
    body_id = event.get("BodyID")
    body_name = event.get("BodyName")
    signals = event.get("Signals")
    if not (
        isinstance(timestamp, str) and timestamp
        and isinstance(body_id, int) and not isinstance(body_id, bool)
        and isinstance(signals, list)
    ):
        return None

    if not star_system:
        return None
    if not (isinstance(star_pos, (list, tuple)) and len(star_pos) == 3):
        return None
    if not isinstance(system_address, int):
        return None

    out_signals: list = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        sig_type = sig.get("Type")
        count = sig.get("Count")
        if not (isinstance(sig_type, str) and sig_type):
            continue
        if not (isinstance(count, int) and not isinstance(count, bool)):
            continue
        out_signals.append({"Type": sig_type, "Count": count})

    if not out_signals:
        return None

    msg: Dict[str, Any] = {
        "timestamp": timestamp,
        "event": "FSSBodySignals",
        "StarSystem": star_system,
        "StarPos": list(star_pos),
        "SystemAddress": system_address,
        "BodyID": body_id,
        "Signals": out_signals,
    }
    if isinstance(body_name, str) and body_name:
        msg["BodyName"] = body_name
    return msg


def build_commodity_message(data: Dict[str, Any], docking_access: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
    dropped_invalid = 0
    for it in items:
        if not isinstance(it, dict):
            dropped_invalid += 1
            continue
        raw_name = it.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            dropped_invalid += 1
            continue
        symbol = _commodity_symbol(raw_name)
        if not symbol:
            dropped_invalid += 1
            continue
        category = it.get("Category")
        is_nonmarketable = symbol == _NONMARKETABLE_SYMBOL or (
            isinstance(category, str) and "nonmarketable" in category.lower()
        )
        if is_nonmarketable:
            continue

        mean_price = it.get("MeanPrice")
        buy_price = it.get("BuyPrice")
        stock = it.get("Stock")
        stock_bracket = it.get("StockBracket")
        sell_price = it.get("SellPrice")
        demand = it.get("Demand")
        demand_bracket = it.get("DemandBracket")
        if not all(
            isinstance(v, int) and not isinstance(v, bool)
            for v in (mean_price, buy_price, stock, sell_price, demand)
        ):
            dropped_invalid += 1
            continue
        if isinstance(stock_bracket, bool) or stock_bracket not in (0, 1, 2, 3, ""):
            dropped_invalid += 1
            continue
        if isinstance(demand_bracket, bool) or demand_bracket not in (0, 1, 2, 3, ""):
            dropped_invalid += 1
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

    if dropped_invalid:
        log.warning(
            "EDDN commodity message for %r/%r dropped %d malformed item(s)",
            station_name, market_id, dropped_invalid,
        )

    if not commodities:
        return None

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


class EddnPublisher:
    """
    Call observe() on every raw journal event unconditionally (cheap —
    just tracks session header fields). Call maybe_publish() only when
    the user has EDDN contribution enabled.
    """

    def __init__(self):
        self._commander: str = ""
        self._horizons: bool = True
        self._odyssey: bool = True
        self._gameversion: str = ""
        self._gamebuild: str = ""
        self._is_beta: bool = False

        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="EddnPublisher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Join briefly so an in-flight POST can finish; the worker loop
        # drains whatever remains in the queue before it exits.
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def observe(self, event: Dict[str, Any]) -> None:
        """Keep session header fields current — call for every raw journal event."""
        name = event.get("event")
        if not isinstance(name, str):
            return

        if name.lower() == "fileheader":
            gv = event.get("gameversion")
            gb = event.get("build")
            od = event.get("odyssey")
            if gv:
                self._gameversion = gv
                self._is_beta = "beta" in gv.lower()
            if gb:
                self._gamebuild = gb
            if isinstance(od, bool):
                self._odyssey = od
            return

        if name == "Commander":
            cmdr = event.get("Name")
            if cmdr:
                self._commander = cmdr
            return

        if name == "LoadGame":
            cmdr = event.get("Commander")
            if cmdr:
                self._commander = cmdr
            h = event.get("Horizons")
            o = event.get("Odyssey")
            gv = event.get("gameversion")
            gb = event.get("build")
            if isinstance(h, bool):
                self._horizons = h
            if isinstance(o, bool):
                self._odyssey = o
            if gv:
                self._gameversion = gv
                self._is_beta = "beta" in gv.lower()
            if gb:
                self._gamebuild = gb

    def maybe_publish(
        self,
        event: Dict[str, Any],
        star_system: str,
        star_pos: Optional[Sequence[float]],
        system_address: Optional[int],
    ) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_message(event, star_system, star_pos, system_address)
        if msg is None:
            return

        payload = {
            "$schemaRef": _SCHEMA_REF,
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
            log.warning("EDDN publish queue full — dropping message")

    def maybe_publish_fssbodysignals(
        self,
        event: Dict[str, Any],
        star_system: str,
        star_pos: Optional[Sequence[float]],
        system_address: Optional[int],
    ) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_fssbodysignals_message(event, star_system, star_pos, system_address)
        if msg is None:
            return

        msg["horizons"] = self._horizons
        msg["odyssey"] = self._odyssey

        payload = {
            "$schemaRef": _FSSBODYSIGNALS_SCHEMA_REF,
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
            log.warning("EDDN publish queue full — dropping fssbodysignals message")

    def maybe_publish_commodity(self, data: Dict[str, Any], docking_access: Optional[str] = None) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_commodity_message(data, docking_access)
        if msg is None:
            return

        msg["horizons"] = self._horizons
        msg["odyssey"] = self._odyssey

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

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._send_with_retry(payload)
        # Stop requested — drain anything still queued (best-effort, one
        # pass; failed sends requeue via Timer only if attempts remain,
        # but those timers are daemon so they can't hang process exit).
        while True:
            try:
                payload = self._queue.get_nowait()
            except queue.Empty:
                return
            self._send_with_retry(payload)

    def _send_with_retry(self, payload: Dict[str, Any]) -> None:
        # _retry_attempts is bookkeeping, never part of the wire payload.
        body = {k: v for k, v in payload.items() if k != "_retry_attempts"}
        try:
            resp = requests.post(_GATEWAY_URL, json=body, timeout=_POST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("EDDN publish failed: %s", exc)
        else:
            if resp.status_code == 200:
                return
            log.warning("EDDN gateway rejected message (status %s): %s", resp.status_code, resp.text[:300])
            if not (resp.status_code == 429 or resp.status_code >= 500):
                # Permanent rejection (e.g. schema validation failure) --
                # retrying won't help, so drop it instead of looping forever.
                return

        # Per EDDN dev docs: wait >= 60s before retrying a failed message,
        # and don't block other queued messages meanwhile. Daemon timer —
        # a pending retry must never keep the process alive after shutdown.
        attempts = int(payload.get("_retry_attempts", 0)) + 1
        if attempts >= _RETRY_MAX_ATTEMPTS:
            log.warning(
                "EDDN publish gave up after %d attempts — dropping message",
                attempts,
            )
            return
        payload["_retry_attempts"] = attempts
        timer = threading.Timer(_RETRY_DELAY_SECONDS, self._requeue, args=(payload,))
        timer.daemon = True
        timer.start()

    def _requeue(self, payload: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            log.warning("EDDN publish queue full on retry — dropping message")
