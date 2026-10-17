# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""EDDN publisher — contributes data back to the shared Elite Dangerous
Data Network, the same feed Spansh/EDSM/Inara consume from. Two schemas:

- journal/1 — Docked, FSDJump, Scan, Location, SAASignalsFound,
  CarrierJump events. CodexEntry goes to its own codexentry/1 schema. Everything else is silently skipped
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

import collections
import copy
import json
import logging
import queue
import threading
from typing import Any, Dict, Optional, Sequence

import requests

from edc.version import APP_VERSION

log = logging.getLogger(__name__)

_GATEWAY_URL = "https://eddn.edcd.io:4430/upload/"
_SCHEMA_REF = "https://eddn.edcd.io/schemas/journal/1"
_COMMODITY_SCHEMA_REF = "https://eddn.edcd.io/schemas/commodity/3"
_FCMATERIALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"
_FSSBODYSIGNALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fssbodysignals/1"
_CODEXENTRY_SCHEMA_REF = "https://eddn.edcd.io/schemas/codexentry/1"
_OUTFITTING_SCHEMA_REF = "https://eddn.edcd.io/schemas/outfitting/2"
_SHIPYARD_SCHEMA_REF = "https://eddn.edcd.io/schemas/shipyard/2"
_FSSSIGNAL_SCHEMA_REF = "https://eddn.edcd.io/schemas/fsssignaldiscovered/1"
_ARRIVAL_EVENTS = ("Location", "FSDJump", "CarrierJump")
# codexentry-v1.0.json: personal data, never sent
_CODEX_DISALLOWED = {"IsNewEntry", "NewTraitsDiscovered"}

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
_SOFTWARE_VERSION = APP_VERSION
_RECENT_SENT_MAX = 200   # identical-message memory (the game writes some Scans twice)

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

    if name == "CodexEntry":
        return _build_codex_message(msg, star_pos, system_address)

    for key in _TOP_LEVEL_DISALLOWED:
        msg.pop(key, None)

    factions = msg.get("Factions")
    if isinstance(factions, list):
        for f in factions:
            if isinstance(f, dict):
                for key in _FACTION_DISALLOWED:
                    f.pop(key, None)

    # EDDN's Developers.md: "if the source data only has SystemAddress then
    # you MUST check that it matches that from the prior Location, FSDJump
    # or CarrierJump event before adding StarSystem and StarPos data... Drop
    # the message entirely if it does not match. Apply similar logic if it
    # is only the system's name that is already present." Our tracked
    # star_system/star_pos/system_address (the caller's current-system
    # state) are only valid to graft onto this event if the event's own
    # identifiers, where present, actually agree -- a known journal-writing
    # gap can otherwise leave our tracked state one system behind the event
    # actually being processed.
    existing_system_address = msg.get("SystemAddress")
    if (isinstance(existing_system_address, int) and isinstance(system_address, int)
            and existing_system_address != system_address):
        return None
    existing_star_system = msg.get("StarSystem")
    if (isinstance(existing_star_system, str) and existing_star_system
            and star_system and existing_star_system != star_system):
        return None

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


def _build_codex_message(msg: Dict[str, Any], star_pos, system_address) -> Optional[Dict[str, Any]]:
    """codexentry/1 body: the event already carries System/SystemAddress; add
    StarPos only when SystemAddress matches our tracked system (Developers.md
    location cross-check). BodyID/BodyName are dropped -- the schema allows them
    only after a Status.json cross-check we don't do (codexentry-README:37-103)."""
    for key in _CODEX_DISALLOWED | {"BodyID", "BodyName"}:
        msg.pop(key, None)
    if not (isinstance(msg.get("System"), str) and msg["System"] and isinstance(msg.get("EntryID"), int)
            and isinstance(msg.get("SystemAddress"), int) and msg["SystemAddress"] == system_address
            and isinstance(star_pos, (list, tuple)) and len(star_pos) == 3):
        return None
    msg["StarPos"] = list(star_pos)
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

        commodity = {
            "name": symbol,
            "meanPrice": mean_price,
            "buyPrice": buy_price,
            "stock": stock,
            "stockBracket": stock_bracket,
            "sellPrice": sell_price,
            "demand": demand,
            "demandBracket": demand_bracket,
        }
        # commodity-README "Statusflags": the optional augmentation built from
        # Market.json's Producer/Consumer/Rare booleans (never an empty list).
        flags = [k for k in ("Producer", "Consumer", "Rare") if it.get(k) is True]
        if flags:
            commodity["statusFlags"] = flags
        commodities.append(commodity)

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
    # The schema defines stationType ("renamed" from StationType) and wins over the
    # README's elision list where they differ; all four reference senders use it.
    if isinstance(data.get("StationType"), str) and data["StationType"]:
        msg["stationType"] = data["StationType"]
    if isinstance(docking_access, str) and docking_access:
        msg["carrierDockingAccess"] = docking_access
    return msg


def _station_header(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """systemName/stationName/marketId/timestamp from an Outfitting.json or
    Shipyard.json dict (schema renames), or None if any is missing."""
    if not isinstance(data, dict):
        return None
    system, station, market_id, ts = (data.get(k) for k in ("StarSystem", "StationName", "MarketID", "timestamp"))
    if not (isinstance(system, str) and system and isinstance(station, str) and station
            and isinstance(market_id, int) and isinstance(ts, str) and ts):
        return None
    return {"systemName": system, "stationName": station, "marketId": market_id, "timestamp": ts}


def build_outfitting_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """outfitting/2 body from Outfitting.json: module names only, minus anything
    that depends on the Cmdr rather than the station (outfitting-README
    "Elisions"; the journal has no sku, so only the name rules apply)."""
    msg = _station_header(data)
    items = data.get("Items") if isinstance(data, dict) else None
    if msg is None or not isinstance(items, list):
        return None
    modules = []
    for it in items:
        name = it.get("Name") if isinstance(it, dict) else None
        low = name.lower() if isinstance(name, str) else ""
        if ((low.startswith(("hpt_", "int_")) or "_armour_" in low)
                and low != "int_planetapproachsuite" and name not in modules):
            modules.append(name)
    if not modules:
        return None
    msg["modules"] = modules
    return msg


def build_shipyard_message(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """shipyard/2 body from Shipyard.json: the PriceList ship names."""
    msg = _station_header(data)
    prices = data.get("PriceList") if isinstance(data, dict) else None
    if msg is None or not isinstance(prices, list):
        return None
    ships = []
    for p in prices:
        name = p.get("ShipType") if isinstance(p, dict) else None
        if isinstance(name, str) and name and name not in ships:
            ships.append(name)
    if not ships:
        return None
    msg["ships"] = ships
    if isinstance(data.get("AllowCobraMkIV"), bool):
        msg["allowCobraMkIV"] = data["AllowCobraMkIV"]
    return msg


def build_fsssignal_message(signals: list, star_system: str, star_pos, system_address) -> Optional[Dict[str, Any]]:
    """fsssignaldiscovered/1 body from a contiguous run of FSSSignalDiscovered
    events (fsssignaldiscovered-README): each signal must match the tracked
    SystemAddress; mission-target USS dropped; event, SystemAddress,
    TimeRemaining and *_Localised removed from each signal."""
    if not (star_system and isinstance(system_address, int)
            and isinstance(star_pos, (list, tuple)) and len(star_pos) == 3):
        return None
    out = []
    for evt in signals:
        if evt.get("SystemAddress") != system_address or evt.get("USSType") == "$USS_Type_MissionTarget;":
            continue
        sig = _strip_localised(copy.deepcopy(evt))
        for key in ("event", "SystemAddress", "TimeRemaining"):
            sig.pop(key, None)
        if isinstance(sig.get("timestamp"), str) and isinstance(sig.get("SignalName"), str):
            out.append(sig)
    if not out:
        return None
    return {"event": "FSSSignalDiscovered", "timestamp": out[0]["timestamp"], "SystemAddress": system_address,
            "StarSystem": star_system, "StarPos": list(star_pos), "signals": out}


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
        # None means "not yet known" -- per EDDN's Developers.md: "if you
        # cannot determine a value do not include that key at all" (no
        # `null`, and NOT even `false` as a placeholder). The only
        # authoritative source for these is the journal's own LoadGame
        # event; a hardcoded True default here would send a real but
        # unverified claim before LoadGame has actually been observed
        # this session.
        self._horizons: Optional[bool] = None
        self._odyssey: Optional[bool] = None
        self._gameversion: str = ""
        self._gamebuild: str = ""
        self._is_beta: bool = False
        self._signal_run: list = []   # contiguous FSSSignalDiscovered events awaiting a batch
        self._recent_sent: "collections.OrderedDict[str, None]" = collections.OrderedDict()

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
            if gv:
                self._gameversion = gv
                self._is_beta = "beta" in gv.lower()
            if gb:
                self._gamebuild = gb
            # Fileheader's own "Odyssey" flag has different semantics from
            # LoadGame's (it indicates a 4.0-vs-3.8 client, not whether the
            # Odyssey expansion is actually owned/active -- confirmed by
            # EDDN's own docs table: a Horizons-4.0 client with no Odyssey
            # shows Fileheader Odyssey:true but LoadGame Odyssey:false).
            # Not used here; LoadGame below is the only correct source.
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

    def _apply_horizons_odyssey(self, msg: Dict[str, Any]) -> None:
        """Sets horizons/odyssey on msg only once actually known -- per
        EDDN's Developers.md, omit the key entirely rather than guess."""
        if self._horizons is not None:
            msg["horizons"] = self._horizons
        if self._odyssey is not None:
            msg["odyssey"] = self._odyssey

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
        self._apply_horizons_odyssey(msg)
        # The game sometimes writes the same event twice (identical line, same
        # timestamp -- seen on arrival-star AutoScans); send it once.
        key = json.dumps(msg, sort_keys=True)
        if key in self._recent_sent:
            return
        self._recent_sent[key] = None
        if len(self._recent_sent) > _RECENT_SENT_MAX:
            self._recent_sent.popitem(last=False)

        payload = {
            "$schemaRef": _CODEXENTRY_SCHEMA_REF if event.get("event") == "CodexEntry" else _SCHEMA_REF,
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

        self._apply_horizons_odyssey(msg)

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

        self._apply_horizons_odyssey(msg)

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

    def batch_signals(self, event: Dict[str, Any], star_system: str, star_pos, system_address) -> None:
        """Call for every live event. FSSSignalDiscovered events are held; the
        first other event sends them as one message, located by that event if
        it's an arrival (Odyssey writes signals before it), else by the tracked
        system (fsssignaldiscovered-README "Batching")."""
        if event.get("event") == "FSSSignalDiscovered":
            self._signal_run.append(event)
            return
        if not self._signal_run:
            return
        run, self._signal_run = self._signal_run, []
        if event.get("event") in _ARRIVAL_EVENTS:
            star_system, star_pos, system_address = (event.get("StarSystem"), event.get("StarPos"),
                                                     event.get("SystemAddress"))
        if self._is_beta or not self._commander:
            return
        msg = build_fsssignal_message(run, star_system, star_pos, system_address)
        if msg is None:
            return
        self._apply_horizons_odyssey(msg)
        payload = {
            "$schemaRef": _FSSSIGNAL_SCHEMA_REF,
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
            log.warning("EDDN publish queue full — dropping fsssignaldiscovered message")

    def maybe_publish_station_list(self, kind: str, data: Dict[str, Any]) -> None:
        """kind "outfitting" (Outfitting.json) or "shipyard" (Shipyard.json)."""
        if self._is_beta or not self._commander:
            return
        build, ref = ((build_outfitting_message, _OUTFITTING_SCHEMA_REF) if kind == "outfitting"
                      else (build_shipyard_message, _SHIPYARD_SCHEMA_REF))
        msg = build(data)
        if msg is None:
            return
        self._apply_horizons_odyssey(msg)
        payload = {
            "$schemaRef": ref,
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
            log.warning("EDDN publish queue full — dropping %s message", kind)

    def maybe_publish_fcmaterials(self, data: Dict[str, Any]) -> None:
        if self._is_beta:
            return
        if not self._commander:
            return

        msg = build_fcmaterials_message(data)
        if msg is None:
            return

        self._apply_horizons_odyssey(msg)

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
