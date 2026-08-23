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
_FCMATERIALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fcmaterials_journal/"
_RELEVANT_EVENTS = {"FSDJump", "Location", "CarrierJump", "Docked", "CodexEntry"}
_RECV_TIMEOUT_MS = 5000
_RECONNECT_DELAY_S = 5

# A ZMQ SUB socket has no built-in way to detect a peer that's silently
# gone away (no TLS/TCP-level signal, recv() just keeps timing out with
# Again forever) -- confirmed live: our own connection went quiet for
# over an hour with zero errors logged, while a fresh connection to the
# same relay pulled 442 messages in 30s. EliteBGS (elite-kode/elitebgs),
# a real production EDDN consumer, uses this same "reconnect after N
# seconds of total silence" watchdog against this exact relay, at the
# same 300s threshold -- kept identical here rather than inventing a new
# number, since it's already proven against EDDN's real traffic pattern.
_STALE_CONNECTION_TIMEOUT_S = 300

# EDDN is public/unmoderated at the transport level — zlib.decompress() has
# no built-in size cap, so a corrupted or oversized message could decompress
# to something huge ("zip bomb" pattern) and stall/crash the listener on a
# pathologically large json.loads() call. Real EDDN messages are KBs; 10MB
# is generous headroom while still rejecting anything that isn't legitimate.
_MAX_DECOMPRESSED_BYTES = 10 * 1024 * 1024

_FSSSIGNALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fsssignaldiscovered/"


def _extract_bgs_status(msg: dict) -> tuple[list, list]:
    """War/CivilWar conflicts and multi-state factions from a journal
    message's Conflicts/Factions arrays -- unconditional (any system, not
    just a squadron-watched faction), unlike _maybe_emit_faction_seen."""
    conflicts = [
        c for c in (msg.get("Conflicts") or [])
        if isinstance(c, dict) and str(c.get("WarType", "")).lower() in ("war", "civilwar")
    ]
    factions = [
        f for f in (msg.get("Factions") or [])
        if isinstance(f, dict) and (f.get("ActiveStates") or f.get("PendingStates") or f.get("RecoveringStates"))
    ]
    return conflicts, factions


def _extract_res_tiers(msg: dict) -> list:
    """Sorted, deduped RES tiers from an fsssignaldiscovered message's
    signals array."""
    from edc.core.res_signals import res_tier_from_signal_name

    tiers = set()
    for sig in (msg.get("signals") or []):
        if not isinstance(sig, dict):
            continue
        if sig.get("SignalType") != "ResourceExtraction":
            continue
        name = sig.get("SignalName_Localised") or sig.get("SignalName") or ""
        tiers.add(res_tier_from_signal_name(name))
    return sorted(tiers)


def _safe_decompress(raw: bytes) -> bytes | None:
    """Returns the decompressed bytes, or None if decompression failed or
    would exceed _MAX_DECOMPRESSED_BYTES (in which case the message is
    discarded rather than risking an unbounded-size json.loads() call)."""
    try:
        decompressor = zlib.decompressobj()
        out = decompressor.decompress(raw, _MAX_DECOMPRESSED_BYTES)
        if decompressor.unconsumed_tail:
            log.warning("Discarding oversized EDDN message (exceeded %d bytes decompressed)", _MAX_DECOMPRESSED_BYTES)
            return None
        return out
    except Exception:
        return None


class EddnPowerPlayWorker(QObject):
    # id64 (SystemAddress) is a 64-bit value — pyqtSignal(int, ...) silently
    # truncates to 32 bits (confirmed: PyQt maps "int" to C++ int), corrupting
    # any SystemAddress above ~2.1 billion. Declared as "object" instead to
    # pass the Python int through unmodified.
    system_seen = pyqtSignal(object, str, str, str)  # id64, power, power_state, timestamp
    system_coords_seen = pyqtSignal(str, float, float, float)  # StarSystem, x, y, z
    commodity_seen = pyqtSignal(dict)  # raw commodity/3 message body
    fcmaterials_seen = pyqtSignal(dict)  # raw fcmaterials_journal/1 message body
    # Raw journal/1 Docked message body — same shape extract_station_info()
    # already parses for our own dockings, just sourced from other
    # commanders' visits too (the same crowdsourcing model Inara/EDSM use
    # for station-service data, rather than being limited to our own).
    station_seen = pyqtSignal(dict)
    # Raw journal/1 CodexEntry message body, filtered to biology entries only
    # — species are deterministic per body, so another commander's already-
    # reported find tells us exactly what's there before we personally DSS it.
    codex_entry_seen = pyqtSignal(dict)
    # id64, StarSystem, faction record (dict), is_controlling, timestamp — only
    # emitted for factions in watched_factions, so this stays rare rather than
    # firing on every journal/1 message network-wide.
    faction_seen = pyqtSignal(object, str, dict, bool, str)
    # id64, StarSystem, war conflicts (list), multi-state factions (list),
    # timestamp -- unconditional (any system), unlike faction_seen which is
    # gated to watched_factions. Feeds system_bgs_status.
    bgs_status_seen = pyqtSignal(object, str, list, list, str)
    # id64, StarSystem, RES tiers present (list), timestamp. Feeds
    # system_res_sites.
    res_signal_seen = pyqtSignal(object, str, list, str)
    finished = pyqtSignal()

    def __init__(self, watched_factions=None):
        super().__init__()
        self._stop = False
        # Fixed at construction (squadron-aligned faction rarely changes) —
        # a set of faction names to watch for in EDDN's Factions array, so
        # we can build presence data for systems the player never personally
        # visits, the same way Inara/EDSM's own BGS tools do.
        self._watched_factions = set(watched_factions or ())

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
        last_message_time = time.monotonic()
        while not self._stop:
            try:
                raw = sub.recv()
            except zmq.error.Again:
                # recv timeout -- normally just gives us a chance to check
                # self._stop, but if it's been happening for too long the
                # connection is likely stale (see _STALE_CONNECTION_TIMEOUT_S)
                # rather than genuinely quiet -- force a reconnect.
                if time.monotonic() - last_message_time > _STALE_CONNECTION_TIMEOUT_S:
                    log.warning(
                        "EDDN listener: no messages received in over %ds — "
                        "connection likely stale, forcing reconnect",
                        _STALE_CONNECTION_TIMEOUT_S,
                    )
                    return
                continue
            last_message_time = time.monotonic()
            decompressed = _safe_decompress(raw)
            if decompressed is None:
                continue
            try:
                data = json.loads(decompressed)
            except Exception:
                continue

            schema = data.get("$schemaRef") or ""

            if schema.startswith(_COMMODITY_SCHEMA_PREFIX):
                msg = data.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("commodities"), list):
                    self.commodity_seen.emit(msg)
                continue

            if schema.startswith(_FCMATERIALS_SCHEMA_PREFIX):
                msg = data.get("message")
                if (isinstance(msg, dict) and isinstance(msg.get("MarketID"), int)
                        and isinstance(msg.get("Items"), list)):
                    self.fcmaterials_seen.emit(msg)
                continue

            if schema.startswith(_FSSSIGNALS_SCHEMA_PREFIX):
                msg = data.get("message")
                if isinstance(msg, dict):
                    self._maybe_emit_res_signal(msg)
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

            if msg.get("event") == "Docked":
                # No PowerPlay fields on Docked messages — handled entirely
                # separately from the FSDJump/Location/CarrierJump path below.
                if isinstance(msg.get("MarketID"), int):
                    self.station_seen.emit(msg)
                continue

            if msg.get("event") == "CodexEntry":
                category = str(msg.get("Category_Localised") or msg.get("Category") or "")
                if ("biology" in category.lower()
                        and isinstance(msg.get("SystemAddress"), int)
                        and isinstance(msg.get("BodyID"), int)
                        and isinstance(msg.get("Name_Localised"), str) and msg.get("Name_Localised")):
                    self.codex_entry_seen.emit(msg)
                continue

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

            if self._watched_factions:
                self._maybe_emit_faction_seen(msg, timestamp)

            self._maybe_emit_bgs_status(msg, timestamp)

    def _maybe_emit_faction_seen(self, msg: dict, timestamp: str) -> None:
        factions = msg.get("Factions")
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        if not (isinstance(factions, list) and isinstance(system_address, int)
                and system_address > 0 and isinstance(star_system, str) and star_system):
            return

        target = None
        best_name = None
        best_influence = -1.0
        for f in factions:
            if not isinstance(f, dict):
                continue
            name = f.get("Name")
            influence = f.get("Influence")
            if isinstance(influence, (int, float)) and influence > best_influence:
                best_influence = influence
                best_name = name
            if name in self._watched_factions:
                target = f

        if target is None:
            return

        # EDDN's schema doesn't include SystemFaction (that field is
        # journal-only) — highest Influence among all factions in this same
        # message is used as an is_controlling heuristic instead.
        is_controlling = bool(best_name and target.get("Name") == best_name)
        self.faction_seen.emit(system_address, star_system, dict(target), is_controlling, timestamp)

    def _maybe_emit_bgs_status(self, msg: dict, timestamp: str) -> None:
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(star_system, str) and star_system):
            return
        conflicts, factions = _extract_bgs_status(msg)
        if not conflicts and not factions:
            return
        self.bgs_status_seen.emit(system_address, star_system, conflicts, factions, timestamp)

    def _maybe_emit_res_signal(self, msg: dict) -> None:
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(star_system, str) and star_system):
            return
        tiers = _extract_res_tiers(msg)
        if not tiers:
            return
        timestamp = msg.get("timestamp") or ""
        self.res_signal_seen.emit(system_address, star_system, tiers, timestamp)
