# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Opt-in sender: uploads the commander's live journal events to EDSM using
EDMC's EDSM plugin rules. HTTP runs on a background worker thread; the thread
never touches SQLite and the API key is never logged."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from edc.version import USER_AGENT

log = logging.getLogger(__name__)

_QUEUE_MAX = 200
_TIMEOUT = 15
_DISCARD_RETRY = 60   # seconds between discard-list fetches until one arrives
_MAX_ATTEMPTS = 3
_URL = "https://www.edsm.net/api-journal-v1"
_clock = time.time    # epoch seconds, compared with X-Rate-Limit-Reset
LOCATION_EVENTS = ("CarrierJump", "FSDJump", "Location", "Docked")
_SKIPPED = ("CommunityGoal", "ModuleBuy", "ModuleSell", "ModuleSwap", "ShipyardBuy", "ShipyardNew", "ShipyardSwap")


def should_send(pending: List[Dict[str, Any]], event: str, newgame_docked: bool) -> bool:
    # EDMC's NavBeaconScan special case is skipped: the app has no equivalent counter.
    if event.lower() in ("shutdown", "fileheader"):
        return True

    def wanted(e: Dict[str, Any]) -> bool:
        if e["event"] == "Cargo":
            return not newgame_docked
        return e["event"] == "Docked" or e["event"] not in _SKIPPED
    return any(wanted(e) for e in pending)


def with_transient(evt: Dict[str, Any], system: str, coords: tuple, station: Optional[str],
                   ship_id: Optional[int]) -> Dict[str, Any]:
    return {**evt, "_systemName": system, "_systemCoordinates": coords,
            "_stationName": station, "_shipId": ship_id}


def check_key(commander_name: str, key: str) -> bool:
    """True when EDSM accepts the commander/key pair. Synchronous."""
    try:
        resp = requests.post(_URL, data={"commanderName": commander_name, "apiKey": key,
                                         "fromSoftware": "EDChronicle", "message": "[]"},
                             headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
        return resp.json()["msgnum"] // 100 == 1
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        log.warning("EDSM key check failed: %s", type(exc).__name__)
        return False


class EdsmPusher:
    def __init__(self, commander_name: str, key: str, software: str, version: str,
                 on_status: Callable[[str], None]):
        self._cmdr = commander_name
        self._key = key
        self._software = software
        self._version = version
        self._on_status = on_status
        self._game: Tuple[str, str] = ("", "")
        self._last_game: Tuple[str, str] = ("", "")
        self._discards: Optional[Set[str]] = None
        self._pending: List[Dict[str, Any]] = []
        self._newgame_docked = False
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="EdsmPusher", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def set_game(self, gameversion: str, gamebuild: str) -> None:
        self._game = (gameversion, gamebuild)

    def submit(self, evt: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((evt, self._game))
        except queue.Full:
            log.warning("EDSM queue full — dropping %s", evt.get("event"))

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if self._discards is None:
                if not self._fetch_discards():
                    self._stop.wait(_DISCARD_RETRY)
                continue
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._handle(*item)
        if self._pending and self._discards is not None:
            self._send(self._last_game, closing=True)

    def _fetch_discards(self) -> bool:
        try:
            r = requests.get(f"{_URL}/discard", headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
            r.raise_for_status()
            found = set(r.json())
            found.discard("Docked")   # should_send assumes Docked is always sent
            if found:
                self._discards = found
                return True
        except Exception as exc:
            log.warning("EDSM discard list failed: %s", type(exc).__name__)
        return False

    def _handle(self, evt: Dict[str, Any], game: Tuple[str, str]) -> None:
        try:
            name = evt["event"]
            if name in ("LoadGame", "Location"):
                self._newgame_docked = bool(evt.get("Docked"))
            elif name == "Undocked":
                self._newgame_docked = False
            if name not in self._discards:
                # one batch claims one game version, so never mix versions or journal files
                if name.lower() == "fileheader" or game != self._last_game:
                    self._pending = []
                self._pending.append(evt)
            if self._pending and should_send(self._pending, name, self._newgame_docked):
                self._send(game, closing=False)
            if name.lower() in ("shutdown", "commander", "fileheader"):
                self._pending = []
            self._last_game = game
        except Exception as exc:
            log.warning("EDSM send failed: %s", type(exc).__name__)
            self._on_status("EDSM: send failed")

    def _send(self, game: Tuple[str, str], closing: bool) -> None:
        data = {"commanderName": self._cmdr, "apiKey": self._key, "fromSoftware": self._software,
                "fromSoftwareVersion": self._version, "fromGameVersion": game[0],
                "fromGameBuild": game[1], "message": json.dumps(self._pending, ensure_ascii=False)}
        for _ in range(1 if closing else _MAX_ATTEMPTS):
            try:
                resp = requests.post(_URL, data=data, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)
                if resp.status_code == 429:
                    reset = resp.headers.get("X-Rate-Limit-Reset") or ""
                    if closing or not reset.isdigit():
                        break
                    self._stop.wait(max(0, int(reset) - _clock()))
                    continue
                resp.raise_for_status()
                msgnum = resp.json()["msgnum"]
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                log.warning("EDSM send failed: %s", type(exc).__name__)
                continue
            if msgnum // 100 == 5:   # saved server-side for later; keep and resend
                return
            if msgnum // 100 == 2:
                log.warning("EDSM refused batch: msgnum %s", msgnum)
                self._on_status(f"EDSM: refused ({msgnum})")
            else:
                self._on_status(f"EDSM: sent {len(self._pending)} events")
            self._pending = []
            return
        self._on_status("EDSM: send failed")
