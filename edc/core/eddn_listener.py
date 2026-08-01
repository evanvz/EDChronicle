"""Persistent background listener subscribing to EDDN's live relay for PowerPlay data.

Runs on its own QThread for the lifetime of the app. Filters the
journal schema for events that carry ControllingPower/PowerplayState
verbatim (FSDJump/Location/CarrierJump — confirmed empirically) and
emits one signal per sighting; the cache mutation itself happens on
the main thread via the connected slot, so no cross-thread dict access
is needed.
"""
from __future__ import annotations

import logging
import time
import zlib
import json

from PyQt6.QtCore import QObject, pyqtSignal
import zmq

log = logging.getLogger(__name__)

_RELAY_URL = "tcp://eddn.edcd.io:9500"
_JOURNAL_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/journal/"
_COMMODITY_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/commodity/"
_RELEVANT_EVENTS = {"FSDJump", "Location", "CarrierJump"}
_RECV_TIMEOUT_MS = 5000
_RECONNECT_DELAY_S = 5


class EddnPowerPlayWorker(QObject):
    system_seen = pyqtSignal(int, str, str, str)  # id64, power, power_state, timestamp
    system_coords_seen = pyqtSignal(str, float, float, float)  # StarSystem, x, y, z
    commodity_seen = pyqtSignal(dict)  # raw commodity/3 message body
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ctx = zmq.Context()
        while not self._stop:
            sub = ctx.socket(zmq.SUB)
            try:
                sub.setsockopt(zmq.SUBSCRIBE, b"")
                sub.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
                sub.connect(_RELAY_URL)
                log.info("EDDN listener connected to %s", _RELAY_URL)
                self._pump(sub)
            except Exception:
                log.exception("EDDN listener error — reconnecting in %ss", _RECONNECT_DELAY_S)
            finally:
                sub.close(linger=0)
            if not self._stop:
                time.sleep(_RECONNECT_DELAY_S)
        ctx.term()
        self.finished.emit()

    def _pump(self, sub) -> None:
        while not self._stop:
            try:
                raw = sub.recv()
            except zmq.error.Again:
                continue  # recv timeout — just gives us a chance to check self._stop
            try:
                data = json.loads(zlib.decompress(raw))
            except Exception:
                continue

            schema = data.get("$schemaRef") or ""

            if schema.startswith(_COMMODITY_SCHEMA_PREFIX):
                msg = data.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("commodities"), list):
                    self.commodity_seen.emit(msg)
                continue

            if not schema.startswith(_JOURNAL_SCHEMA_PREFIX):
                continue

            msg = data.get("message")
            if not isinstance(msg, dict) or msg.get("event") not in _RELEVANT_EVENTS:
                continue

            # Passively harvest system coordinates from whichever journal
            # messages already carry StarPos — feeds the market feature's
            # distance filtering without needing a separate lookup API.
            star_system = msg.get("StarSystem")
            star_pos = msg.get("StarPos")
            if (isinstance(star_system, str) and star_system
                    and isinstance(star_pos, list) and len(star_pos) == 3
                    and all(isinstance(v, (int, float)) for v in star_pos)):
                self.system_coords_seen.emit(star_system, float(star_pos[0]), float(star_pos[1]), float(star_pos[2]))

            power = msg.get("ControllingPower")
            power_state = msg.get("PowerplayState")
            id64 = msg.get("SystemAddress")
            # EDDN is public/unmoderated at the data level — some uploader clients
            # send malformed SystemAddress values (observed: negative ints, likely
            # truncated 32-bit artifacts). Real ones are always positive.
            if not (isinstance(power, str) and power and isinstance(power_state, str) and power_state
                    and isinstance(id64, int) and id64 > 0):
                continue

            timestamp = msg.get("timestamp") or ""
            self.system_seen.emit(id64, power, power_state, timestamp)
