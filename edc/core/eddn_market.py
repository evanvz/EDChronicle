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
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

log = logging.getLogger(__name__)


class EddnMarketCache:

    def __init__(self, repo):
        self._repo = repo
        self._coord_buffer: Dict[str, Tuple[str, float, float, float, str]] = {}
        self._market_buffer: Dict[Tuple[int, str], tuple] = {}

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

    def buffered_counts(self) -> Tuple[int, int]:
        """Returns (coord_count, market_row_count) currently buffered — for status/logging."""
        return len(self._coord_buffer), len(self._market_buffer)

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
