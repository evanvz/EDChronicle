"""Buffers live EDDN commodity/3 messages and system-coordinate sightings
in memory, flushing to SQLite periodically in a single batched transaction.

Deliberately not a QThread worker itself — per this project's established
pattern (see edc/core/eddn_listener.py), the ZeroMQ receive loop runs on a
background thread and only emits Qt signals; this class's methods are
called from main-thread slots connected to those signals, and the actual
SQLite writes happen via the same Repository instance the rest of the app
already uses on the main thread. This avoids ever touching sqlite3 from a
non-owning thread.

Buffering (rather than writing per-message) matters here specifically
because commodity/3 is one of EDDN's highest-volume schemas galaxy-wide —
per-message synchronous writes would be a real bottleneck.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Tuple

from edc.core.eddn_publisher import _commodity_symbol
from edc.core.station_pads import extract_station_info

log = logging.getLogger(__name__)


class EddnMarketCache:

    def __init__(self, repo):
        self._repo = repo
        self._coord_buffer: Dict[str, Tuple[str, float, float, float, str]] = {}
        self._market_buffer: Dict[Tuple[int, str], tuple] = {}
        # (system_name, faction dict, is_controlling, timestamp) keyed by
        # system_address — deduped so re-sightings of the same system
        # between flushes only cost one write, not one per sighting.
        self._faction_buffer: Dict[int, Tuple[str, Dict[str, Any], bool, str]] = {}
        # Keyed by market_id — Docked sightings from any commander network-wide,
        # the same crowdsourcing model Inara/EDSM use for station-service data.
        self._station_buffer: Dict[int, Dict[str, Any]] = {}
        # Keyed by (system_address, body_id) — biology CodexEntry sightings
        # from any commander. Species are deterministic per body, so this
        # tells us exactly what's on a body before we personally DSS it.
        self._codex_buffer: Dict[Tuple[int, int], tuple] = {}
        # Keyed by (market_id, material_symbol) -- Fleet Carrier material
        # listings from fcmaterials_journal/1 sightings, any commander's.
        self._fcmaterials_buffer: Dict[Tuple[int, str], tuple] = {}
        # Keyed by market_id -- a carrier's self-reported docking access
        # from commodity/3's optional carrierDockingAccess field, any
        # commander's. The only data source that can ever answer "can I
        # land here" for someone else's carrier (see module docstring
        # context in this task's design spec) -- coverage is necessarily
        # incomplete since the field is optional.
        self._carrier_access_buffer: Dict[int, Tuple[int, str, str]] = {}
        # Keyed by system_address -- War/CivilWar conflicts + multi-state
        # factions from any commander's journal/1 message, deduped so
        # re-sightings between flushes cost one write, not one per sighting.
        self._bgs_status_buffer: Dict[int, Tuple[str, list, list, str]] = {}
        # Keyed by system_address -- RES tiers present, from any
        # commander's fsssignaldiscovered/1 message.
        self._res_sites_buffer: Dict[int, Tuple[str, list, str]] = {}

    def on_coords_seen(self, system_name: str, x: float, y: float, z: float) -> None:
        if not system_name:
            return
        self._coord_buffer[system_name] = (
            system_name, x, y, z, datetime.now(timezone.utc).isoformat()
        )

    def on_commodity_message(self, msg: Dict[str, Any]) -> None:
        market_id = msg.get("marketId")
        if not isinstance(market_id, int):
            return
        station_name = msg.get("stationName") or ""
        station_type = msg.get("stationType") or ""
        system_name = msg.get("systemName") or ""
        timestamp = msg.get("timestamp") or ""

        docking_access = msg.get("carrierDockingAccess")
        if isinstance(docking_access, str) and docking_access:
            self._carrier_access_buffer[market_id] = (market_id, docking_access, timestamp)

        for c in (msg.get("commodities") or []):
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if not isinstance(name, str) or not name:
                continue
            key = (market_id, name)
            self._market_buffer[key] = (
                market_id, name, station_name, station_type, system_name,
                c.get("sellPrice"), c.get("buyPrice"), c.get("meanPrice"),
                c.get("demand"), c.get("demandBracket"),
                c.get("stock"), c.get("stockBracket"),
                timestamp,
            )

    def on_station_seen(self, msg: Dict[str, Any]) -> None:
        info = extract_station_info(msg)
        if info is not None:
            self._station_buffer[info["market_id"]] = info

    def on_codex_entry_seen(self, msg: Dict[str, Any]) -> None:
        system_address = msg.get("SystemAddress")
        body_id = msg.get("BodyID")
        name_localised = msg.get("Name_Localised")
        if not (isinstance(system_address, int) and isinstance(body_id, int) and name_localised):
            return
        self._codex_buffer[(system_address, body_id)] = (
            system_address, body_id, str(name_localised), str(msg.get("Name") or ""),
            msg.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        )

    def on_faction_seen(self, system_address: int, system_name: str, faction: Dict[str, Any], is_controlling: bool, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._faction_buffer[system_address] = (system_name, faction, is_controlling, timestamp)

    def on_bgs_status_seen(self, system_address: int, system_name: str, conflicts: list, factions: list, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._bgs_status_buffer[system_address] = (system_name, conflicts, factions, timestamp)

    def on_res_signal_seen(self, system_address: int, system_name: str, tiers: list, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._res_sites_buffer[system_address] = (system_name, tiers, timestamp)

    def on_fcmaterials_message(self, msg: Dict[str, Any]) -> None:
        market_id = msg.get("MarketID")
        if not isinstance(market_id, int):
            return
        carrier_name = msg.get("CarrierName") or ""
        carrier_id = msg.get("CarrierID") or ""
        timestamp = msg.get("timestamp") or datetime.now(timezone.utc).isoformat()

        for item in (msg.get("Items") or []):
            if not isinstance(item, dict):
                continue
            name = _commodity_symbol(item.get("Name") or "").lower()
            if not name:
                continue
            key = (market_id, name)
            self._fcmaterials_buffer[key] = (
                market_id, name, carrier_name, carrier_id,
                item.get("Price"), item.get("Stock"), item.get("Demand"),
                timestamp,
            )

    def buffered_counts(self) -> Tuple[int, int, int, int, int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count,
        station_count, fcmaterials_count, carrier_access_count,
        bgs_status_count, res_sites_count) currently buffered -- for
        status/logging."""
        return (
            len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer),
            len(self._station_buffer), len(self._fcmaterials_buffer), len(self._carrier_access_buffer),
            len(self._bgs_status_buffer), len(self._res_sites_buffer),
        )

    def pop_buffers(self):
        """
        Snapshots and clears all nine buffers, returning their contents as
        plain lists/tuples -- for handing off to a background worker with
        its own DB connection (see main_window.py's _EddnFlushWorker).
        Cheap, main-thread-only dict operations; the actual DB writes are
        the expensive part, deliberately not done here.
        """
        coords = list(self._coord_buffer.values())
        market = list(self._market_buffer.values())
        factions = list(self._faction_buffer.items())
        stations = list(self._station_buffer.values())
        codex = list(self._codex_buffer.values())
        fcmaterials = list(self._fcmaterials_buffer.values())
        carrier_access = list(self._carrier_access_buffer.values())
        bgs_status = list(self._bgs_status_buffer.items())
        res_sites = list(self._res_sites_buffer.items())
        self._coord_buffer.clear()
        self._market_buffer.clear()
        self._faction_buffer.clear()
        self._station_buffer.clear()
        self._codex_buffer.clear()
        self._fcmaterials_buffer.clear()
        self._carrier_access_buffer.clear()
        self._bgs_status_buffer.clear()
        self._res_sites_buffer.clear()
        return coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites

    def flush(self) -> None:
        """Synchronous flush on the caller's own thread/connection — only
        safe to call from the main thread (uses self._repo, the main
        thread's connection) and only when blocking briefly is acceptable
        (e.g. on app shutdown). The periodic mid-session flush uses
        pop_buffers() + write_buffers() on a background worker instead —
        this was previously a QTimer-connected slot running directly on
        the main thread every 45s, which froze the UI for however long a
        big buffered batch took to write (confirmed live, worse right
        after docking at a busy station's market)."""
        coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites = self.pop_buffers()
        write_buffers(self._repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites)


def write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites) -> None:
    """The actual writes — factored out so both the main-thread flush()
    (shutdown) and a background worker (periodic, see main_window.py) can
    use the identical logic against whichever Repository they're given."""
    if coords:
        try:
            repo.save_system_coords_batch(coords)
        except Exception:
            log.exception("Failed to flush system_coords batch")

    if market:
        try:
            repo.save_market_snapshot_batch(market)
        except Exception:
            log.exception("Failed to flush market_prices batch")

    if factions:
        for system_address, (system_name, faction, is_controlling, timestamp) in factions:
            try:
                repo.save_system_name_if_missing(system_address, system_name)
                snapshot_date = (timestamp or "")[:10] or date.today().isoformat()
                repo.save_faction_snapshot(
                    system_address, faction, snapshot_date, is_controlling, timestamp or "", "eddn",
                )
            except Exception:
                log.exception("Failed to flush faction sighting for system_address=%s", system_address)

    if stations:
        try:
            repo.save_station_info_batch(stations)
        except Exception:
            log.exception("Failed to flush station_info batch")

    if codex:
        try:
            repo.save_codex_species_sightings_batch(codex)
        except Exception:
            log.exception("Failed to flush codex_species_sightings batch")

    if fcmaterials:
        try:
            repo.save_fleet_carrier_materials_batch(fcmaterials)
        except Exception:
            log.exception("Failed to flush fleet_carrier_materials batch")

    if carrier_access:
        try:
            repo.save_carrier_docking_access_batch(carrier_access)
        except Exception:
            log.exception("Failed to flush carrier_docking_access batch")

    if bgs_status:
        for system_address, (system_name, conflicts, factions_list, timestamp) in bgs_status:
            try:
                repo.save_system_bgs_status(system_address, system_name, conflicts, factions_list, timestamp, "eddn")
            except Exception:
                log.exception("Failed to flush BGS status for system_address=%s", system_address)

    if res_sites:
        for system_address, (system_name, tiers, timestamp) in res_sites:
            try:
                repo.save_system_res_tiers(system_address, system_name, tiers, timestamp, "eddn")
            except Exception:
                log.exception("Failed to flush RES sites for system_address=%s", system_address)
