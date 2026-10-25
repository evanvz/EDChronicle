# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

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
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
import zmq

log = logging.getLogger(__name__)

_RELAY_URL = "tcp://eddn.edcd.io:9500"
_JOURNAL_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/journal/"
_COMMODITY_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/commodity/"
_FCMATERIALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fcmaterials_journal/"
_CODEXENTRY_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/codexentry/"
# The Codex files geology vents and anomalies under Category Biology too; only
# this subcategory is exobiology species (Canonn codex ref, 2026-10-17).
_SPECIES_SUBCATEGORY = "$Codex_SubCategory_Organic_Structures;"
_RELEVANT_EVENTS = {"FSDJump", "Location", "CarrierJump", "Docked", "CodexEntry", "Scan"}
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
# EDDataHub's LAN pass-through (config eddn_relay_url): the squadron's server reads
# EDDN once and passes every raw message on, so this app isn't another listener on
# the EDDN relay (which is limiting non-server listeners, 2026-10). Silent this long:
# fall back to EDDN directly, and try the hub again after _HUB_RETRY_S.
_HUB_SILENT_S = 30
_HUB_RETRY_S = 600

# EDDN is public/unmoderated at the transport level — zlib.decompress() has
# no built-in size cap, so a corrupted or oversized message could decompress
# to something huge ("zip bomb" pattern) and stall/crash the listener on a
# pathologically large json.loads() call. Real EDDN messages are KBs; 10MB
# is generous headroom while still rejecting anything that isn't legitimate.
_MAX_DECOMPRESSED_BYTES = 10 * 1024 * 1024

_FSSSIGNALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fsssignaldiscovered/"
_FSSBODYSIGNALS_SCHEMA_PREFIX = "https://eddn.edcd.io/schemas/fssbodysignals/"


def _extract_bgs_status(msg: dict) -> tuple[list, list]:
    """War/CivilWar/Election conflicts and multi-state factions from a journal
    message's Conflicts/Factions arrays -- unconditional (any system, not
    just a squadron-watched faction), unlike _maybe_emit_faction_seen."""
    from edc.core.bgs_conflicts import is_multistate_faction

    conflicts = [
        c for c in (msg.get("Conflicts") or [])
        if isinstance(c, dict) and str(c.get("WarType", "")).lower() in ("war", "civilwar", "election")
    ]
    factions = [
        f for f in (msg.get("Factions") or [])
        if isinstance(f, dict) and is_multistate_faction(f)
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
    # id64, {power: 0-1 acquisition progress}, timestamp -- from other
    # commanders' jumps into Unoccupied/Expansion systems (PowerplayConflictProgress)
    conflict_progress_seen = pyqtSignal(object, dict, str)
    # id64, {"state","reinforcement","undermining","control"}, timestamp --
    # a controlled system's control points this cycle
    control_seen = pyqtSignal(object, dict, str)
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
    # an upload of the system the commander is in (any system): its factions and conflicts
    current_system_seen = pyqtSignal(object, str, dict, bool, str)
    # id64, StarSystem, war conflicts (list), multi-state factions (list),
    # timestamp -- unconditional (any system), unlike faction_seen which is
    # gated to watched_factions. Feeds system_bgs_status.
    bgs_status_seen = pyqtSignal(object, str, list, list, str)
    # id64, StarSystem, names of the factions present (influence > 0), timestamp --
    # only for systems in watched_systems (the Expansion Forecast's candidates).
    faction_names_seen = pyqtSignal(object, str, list, str)
    # id64, event, timestamp -- any commander's jump/dock in a BGS test system
    # (the Experiment Log counts other visitors per tick window).
    system_visit_seen = pyqtSignal(object, str, str)
    # id64, StarSystem, RES tiers present (list), timestamp. Feeds
    # system_res_sites.
    res_signal_seen = pyqtSignal(object, str, list, str)
    # id64, BodyName, {bucket: count} -- whichever of bio/geo/human/
    # guardian/thargoid/mining are present in another commander's
    # fssbodysignals/1 sighting for a body this commander hasn't
    # personally scanned. Feeds net.spansh_bodies.
    body_signals_seen = pyqtSignal(object, str, dict)
    # Raw journal/1 Scan message body, filtered to planetary bodies only
    # (has a non-empty PlanetClass -- excludes stars/belt clusters). Other
    # commanders' live body scans, network-wide -- fresher than Spansh's
    # periodic crawl of the same underlying EDDN firehose, and covers
    # bodies Spansh hasn't caught up on yet. Feeds net.spansh_bodies.
    body_scan_seen = pyqtSignal(dict)
    # id64, StarSystem, profile dict (economy/second_economy/government/
    # security/population/allegiance), timestamp -- real system economy
    # data from another commander's FSDJump/Location/CarrierJump, feeds
    # system_bgs_status so the colonisation candidate dialog can show
    # confirmed economy instead of a body-attribute guess.
    system_profile_seen = pyqtSignal(object, str, dict, str)
    # A BGS tick spotted in the feed (many systems' influence changing at once),
    # our second tick source next to tick.edcd.io -- see edc.core.tick_detector.
    tick_detected = pyqtSignal(str)
    feed_source = pyqtSignal(str)      # "hub" (EDDataHub pass-through) or "direct" (EDDN relay)
    finished = pyqtSignal()

    def __init__(self, watched_factions=None, relay_url: str = ""):
        super().__init__()
        self._stop = False
        self.relay_url = relay_url
        # Fixed at construction (squadron-aligned faction rarely changes) —
        # a set of faction names to watch for in EDDN's Factions array, so
        # we can build presence data for systems the player never personally
        # visits, the same way Inara/EDSM's own BGS tools do.
        self._watched_factions = set(watched_factions or [])
        # Expansion Forecast candidate systems; swapped whole from the UI thread
        # by set_watched_systems() (a single reference assignment).
        self._watched_systems: frozenset = frozenset()
        self._experiment_systems: frozenset = frozenset()   # BGS test systems, same swap pattern
        from edc.core.tick_detector import TickDetector
        self.tick_detector = TickDetector()   # set_last_tick() from the UI thread: one reference swap
        # Diagnostics: per-schema message counts since listener start.
        # Mutated only on the listener thread; read from the UI thread via
        # get_stats() (dict read of ints — GIL makes this safe).
        self._stats = {
            "total": 0,
            "commodity": 0,
            "journal": 0,
            "fcmaterials": 0,
            "fsssignaldiscovered": 0,
            "fssbodysignals": 0,
            "other": 0,
            "invalid": 0,
        }
        self._stats_start = time.monotonic()

    def get_stats(self) -> dict:
        """Snapshot of per-schema counters plus msgs/sec — for the status
        display. Safe to call from any thread."""
        stats = dict(self._stats)
        elapsed = max(time.monotonic() - self._stats_start, 1.0)
        stats["msgs_per_sec"] = round(stats["total"] / elapsed, 1)
        return stats

    def set_experiment_systems(self, addresses) -> None:
        self._experiment_systems = frozenset(addresses)

    def _maybe_emit_visit(self, msg: dict) -> None:
        addr = msg.get("SystemAddress")
        if (addr in self._experiment_systems and isinstance(msg.get("timestamp"), str)
                and msg.get("event") in ("FSDJump", "Location", "CarrierJump", "Docked")):
            self.system_visit_seen.emit(addr, msg.get("event") or "", msg["timestamp"])

    def set_current_system(self, address) -> None:
        """The system the commander is in (one reference swap from the UI thread)."""
        self._current_system = address

    def set_watched_systems(self, addresses) -> None:
        self._watched_systems = frozenset(addresses)

    def stop(self):
        self._stop = True

    def run(self):
        ctx = zmq.Context()
        hub = self.relay_url
        hub_retry_at = 0.0
        while not self._stop:
            use_hub = bool(hub) and time.monotonic() >= hub_retry_at
            url = hub if use_hub else _RELAY_URL
            sub = ctx.socket(zmq.SUB)
            try:
                sub.setsockopt(zmq.SUBSCRIBE, b"")
                sub.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
                sub.connect(url)
                log.info("EDDN listener connected to %s", url)
                got = self._pump(sub, stale_s=_HUB_SILENT_S if use_hub else _STALE_CONNECTION_TIMEOUT_S,
                                 source="hub" if use_hub else "direct",
                                 max_s=_HUB_RETRY_S if hub and not use_hub else None)
                if use_hub and not got:
                    log.warning("EDDataHub's EDDN feed silent -- listening to EDDN directly, retrying in %ds",
                                _HUB_RETRY_S)
                    hub_retry_at = time.monotonic() + _HUB_RETRY_S
                    continue
            except Exception:
                log.exception("EDDN listener error — reconnecting in %ss", _RECONNECT_DELAY_S)
            finally:
                sub.close(linger=0)
            if not self._stop:
                time.sleep(_RECONNECT_DELAY_S)
        self.tick_detector.save()
        ctx.term()
        self.finished.emit()

    def _pump(self, sub, stale_s: Optional[float] = None, source: str = "direct",
              max_s: Optional[float] = None) -> bool:
        """Read until stopped, silent for stale_s, or (direct while a hub is set)
        max_s has passed so the hub is tried again. True if anything arrived."""
        if stale_s is None:
            stale_s = _STALE_CONNECTION_TIMEOUT_S
        started = last_message_time = time.monotonic()
        got = False
        while not self._stop:
            if max_s is not None and time.monotonic() - started > max_s:
                return got
            try:
                raw = sub.recv()
            except zmq.error.Again:
                # recv timeout -- normally just gives us a chance to check
                # self._stop, but if it's been happening for too long the
                # connection is likely stale (see _STALE_CONNECTION_TIMEOUT_S)
                # rather than genuinely quiet -- force a reconnect.
                if time.monotonic() - last_message_time > stale_s:
                    log.warning(
                        "EDDN listener: no messages received in over %ds — "
                        "connection likely stale, forcing reconnect",
                        stale_s,
                    )
                    return got
                continue
            last_message_time = time.monotonic()
            if not got:
                got = True
                self.feed_source.emit(source)
            decompressed = _safe_decompress(raw)
            if decompressed is None:
                continue
            try:
                data = json.loads(decompressed)
            except Exception:
                self._stats["invalid"] += 1
                continue

            schema = data.get("$schemaRef") or ""
            self._stats["total"] += 1

            if schema.startswith(_COMMODITY_SCHEMA_PREFIX):
                self._stats["commodity"] += 1
                msg = data.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("commodities"), list):
                    self.commodity_seen.emit(msg)
                continue

            if schema.startswith(_FCMATERIALS_SCHEMA_PREFIX):
                self._stats["fcmaterials"] += 1
                msg = data.get("message")
                if (isinstance(msg, dict) and isinstance(msg.get("MarketID"), int)
                        and isinstance(msg.get("Items"), list)):
                    self.fcmaterials_seen.emit(msg)
                continue

            if schema.startswith(_FSSSIGNALS_SCHEMA_PREFIX):
                self._stats["fsssignaldiscovered"] += 1
                msg = data.get("message")
                if isinstance(msg, dict):
                    self._maybe_emit_res_signal(msg)
                continue

            if schema.startswith(_FSSBODYSIGNALS_SCHEMA_PREFIX):
                self._stats["fssbodysignals"] += 1
                msg = data.get("message")
                if isinstance(msg, dict):
                    self._maybe_emit_body_signals(msg)
                continue

            if schema.startswith(_CODEXENTRY_SCHEMA_PREFIX):
                # Where compliant senders put CodexEntry (journal/1 is the wrong
                # schema for it); no *_Localised names here, the cache resolves
                # the name from EntryID.
                self._stats["other"] += 1
                msg = data.get("message")
                if (isinstance(msg, dict) and msg.get("SubCategory") == _SPECIES_SUBCATEGORY
                        and isinstance(msg.get("SystemAddress"), int) and isinstance(msg.get("BodyID"), int)):
                    self.codex_entry_seen.emit(msg)
                continue

            if not schema.startswith(_JOURNAL_SCHEMA_PREFIX):
                self._stats["other"] += 1
                continue
            self._stats["journal"] += 1

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

            self._maybe_emit_visit(msg)
            if msg.get("event") == "Docked":
                # No PowerPlay fields on Docked messages — handled entirely
                # separately from the FSDJump/Location/CarrierJump path below.
                if isinstance(msg.get("MarketID"), int):
                    self.station_seen.emit(msg)
                continue

            if msg.get("event") == "CodexEntry":
                if (msg.get("SubCategory") == _SPECIES_SUBCATEGORY
                        and isinstance(msg.get("SystemAddress"), int)
                        and isinstance(msg.get("BodyID"), int)
                        and isinstance(msg.get("Name_Localised"), str) and msg.get("Name_Localised")):
                    self.codex_entry_seen.emit(msg)
                continue

            if msg.get("event") == "Scan":
                if (isinstance(msg.get("SystemAddress"), int)
                        and isinstance(msg.get("BodyName"), str) and msg.get("BodyName")
                        and isinstance(msg.get("PlanetClass"), str) and msg.get("PlanetClass")):
                    self.body_scan_seen.emit(msg)
                continue

            self._maybe_emit_bgs_status(msg, msg.get("timestamp") or "")
            tick = self.tick_detector.observe(msg.get("SystemAddress"), msg.get("Factions"), msg.get("timestamp") or "",
                                              uploader=(data.get("header") or {}).get("uploaderID"))
            if tick:
                self.tick_detected.emit(tick)
            self._maybe_emit_system_profile(msg, msg.get("timestamp") or "")
            self._maybe_emit_faction_names(msg, msg.get("timestamp") or "")
            if (msg.get("SystemAddress") == getattr(self, "_current_system", None)
                    and isinstance(msg.get("Factions"), list) and msg["Factions"]):
                self.current_system_seen.emit(
                    msg["SystemAddress"], msg.get("StarSystem") or "",
                    {"SystemFactions": [dict(f) for f in msg["Factions"] if isinstance(f, dict) and f.get("Name")],
                     "SystemConflicts": [dict(c) for c in (msg.get("Conflicts") or []) if isinstance(c, dict)]},
                    False, msg.get("timestamp") or "")

            power = msg.get("ControllingPower")
            power_state = msg.get("PowerplayState")
            id64 = msg.get("SystemAddress")
            # EDDN is public/unmoderated at the data level — some uploader clients
            # send malformed SystemAddress values (observed: negative ints, likely
            # truncated 32-bit artifacts). Real ones are always positive.
            #
            # ControllingPower is only sent at all once a system has an actual
            # controller (Exploited/Fortified/Stronghold/Turmoil) -- an
            # "Unoccupied" system, including one that just lost its
            # controller, reports PowerplayState with no ControllingPower
            # field. Previously required both fields truthy, so a lost
            # controller was silently dropped instead of updating the
            # cache -- the cross-check kept "confirming" a stale Spansh
            # controlling_power forever, since nothing ever told it control
            # had actually been lost (confirmed: a Reinforcement Finder
            # result stayed unflagged after the system it named had already
            # gone uncontrolled). power="" is the explicit "no controller"
            # sighting; get_controller() below treats it as real data, not
            # a missing entry.
            if not (isinstance(power_state, str) and power_state
                    and isinstance(id64, int) and id64 > 0):
                continue
            power = power if isinstance(power, str) else ""

            timestamp = msg.get("timestamp") or ""
            self.system_seen.emit(id64, power, power_state, timestamp)
            progress = {
                p.get("Power"): float(p.get("ConflictProgress"))
                for p in (msg.get("PowerplayConflictProgress") or [])
                if isinstance(p, dict) and isinstance(p.get("Power"), str)
                and isinstance(p.get("ConflictProgress"), (int, float))
            }
            if progress:
                self.conflict_progress_seen.emit(id64, progress, timestamp)
            if "PowerplayStateReinforcement" in msg or "PowerplayStateUndermining" in msg:
                self.control_seen.emit(id64, {
                    "state": power_state, "reinforcement": msg.get("PowerplayStateReinforcement"),
                    "undermining": msg.get("PowerplayStateUndermining"),
                    "control": msg.get("PowerplayStateControlProgress")}, timestamp)

            if self._watched_factions:
                self._maybe_emit_faction_seen(msg, timestamp)

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
        # every faction in the system rides along, so the system's rows all come from
        # the same reading (Arimavante 2026-10-22: EUW's row showed the war active
        # while Cameron's, from an earlier visit, still showed it pending)
        sighting = dict(target)
        sighting["SystemFactions"] = [dict(f) for f in factions if isinstance(f, dict) and f.get("Name")]
        sighting["SystemConflicts"] = [dict(c) for c in (msg.get("Conflicts") or []) if isinstance(c, dict)]
        self.faction_seen.emit(system_address, star_system, sighting, is_controlling, timestamp)

    def _maybe_emit_faction_names(self, msg: dict, timestamp: str) -> None:
        system_address = msg.get("SystemAddress")
        if system_address not in self._watched_systems:
            return
        factions, star_system = msg.get("Factions"), msg.get("StarSystem")
        if not (isinstance(factions, list) and factions and isinstance(star_system, str) and star_system):
            return
        names = [f["Name"] for f in factions
                 if isinstance(f, dict) and isinstance(f.get("Name"), str)
                 and isinstance(f.get("Influence"), (int, float)) and f["Influence"] > 0]
        self.faction_names_seen.emit(system_address, star_system, names, timestamp)

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

    def _maybe_emit_body_signals(self, msg: dict) -> None:
        """Extracts whichever known signal buckets (biological/geological/
        human/guardian/thargoid/mining) are present in a body's Signals[]
        array -- same bucket keywords event_engine.py uses for the
        commander's own live scans, applied here to other commanders'
        fssbodysignals/1 sightings for bodies not yet personally visited."""
        system_address = msg.get("SystemAddress")
        body_name = msg.get("BodyName")
        signals = msg.get("Signals")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(body_name, str) and body_name
                and isinstance(signals, list)):
            return
        found: dict = {}
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            sig_type = str(sig.get("Type") or "").lower()
            count = sig.get("Count")
            if not (isinstance(count, int) and not isinstance(count, bool)):
                continue
            if "biological" in sig_type:
                found["bio"] = count
            elif "geological" in sig_type:
                found["geo"] = count
            elif "human" in sig_type:
                found["human"] = count
            elif "guardian" in sig_type:
                found["guardian"] = count
            elif "thargoid" in sig_type:
                found["thargoid"] = count
            elif "mining" in sig_type:
                found["mining"] = count
        if found:
            self.body_signals_seen.emit(system_address, body_name, found)

    def _maybe_emit_system_profile(self, msg: dict, timestamp: str) -> None:
        system_address = msg.get("SystemAddress")
        star_system = msg.get("StarSystem")
        economy = msg.get("SystemEconomy")
        if not (isinstance(system_address, int) and system_address > 0
                and isinstance(star_system, str) and star_system
                and isinstance(economy, str) and economy):
            return
        profile = {
            "economy":        economy,
            "second_economy": msg.get("SystemSecondEconomy") or "",
            "government":     msg.get("SystemGovernment") or "",
            "security":       msg.get("SystemSecurity") or "",
            "population":     msg.get("Population") if isinstance(msg.get("Population"), int) else None,
            "allegiance":     msg.get("SystemAllegiance") or "",
        }
        self.system_profile_seen.emit(system_address, star_system, profile, timestamp)

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
