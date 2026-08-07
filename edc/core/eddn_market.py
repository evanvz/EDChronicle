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

    def on_faction_seen(self, system_address: int, system_name: str, faction: Dict[str, Any], is_controlling: bool, timestamp: str) -> None:
        if not (isinstance(system_address, int) and system_name):
            return
        self._faction_buffer[system_address] = (system_name, faction, is_controlling, timestamp)

    def buffered_counts(self) -> Tuple[int, int, int, int]:
        """Returns (coord_count, market_row_count, faction_count, station_count) currently buffered — for status/logging."""
        return len(self._coord_buffer), len(self._market_buffer), len(self._faction_buffer), len(self._station_buffer)

    def flush(self) -> None:
        if self._coord_buffer:
            try:
                self._repo.save_system_coords_batch(list(self._coord_buffer.values()))
            except Exception:
                log.exception("Failed to flush system_coords batch")
            self._coord_buffer.clear()

        if self._market_buffer:
            try:
                self._repo.save_market_snapshot_batch(list(self._market_buffer.values()))
            except Exception:
                log.exception("Failed to flush market_prices batch")
            self._market_buffer.clear()

        if self._faction_buffer:
            for system_address, (system_name, faction, is_controlling, timestamp) in self._faction_buffer.items():
                try:
                    self._repo.save_system_name_if_missing(system_address, system_name)
                    snapshot_date = (timestamp or "")[:10] or date.today().isoformat()
                    self._repo.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling)
                except Exception:
                    log.exception("Failed to flush faction sighting for system_address=%s", system_address)
            self._faction_buffer.clear()

        if self._station_buffer:
            try:
                self._repo.save_station_info_batch(list(self._station_buffer.values()))
            except Exception:
                log.exception("Failed to flush station_info batch")
            self._station_buffer.clear()
