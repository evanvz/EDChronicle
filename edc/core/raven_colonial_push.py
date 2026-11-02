# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Opt-in sender: pushes construction-depot "still needed" amounts and
per-commander deliveries to Raven Colonial. HTTP runs on a background worker
thread; the thread never touches SQLite and the API key is never logged."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests

from edc.core.raven_colonial import _BASE_URL, get_project_for_station
from edc.version import USER_AGENT

log = logging.getLogger(__name__)

_QUEUE_MAX = 200
_TIMEOUT = 15
_MISS_TTL = 600   # seconds before a missing build is looked up again
_clock = time.monotonic
_EVENTS = ("ColonisationConstructionDepot", "ColonisationContribution")


def commodity_key(journal_name: str) -> str:
    s = journal_name[1:] if journal_name.startswith("$") else journal_name
    if s.endswith("_name;"):
        s = s[: -len("_name;")]
    return s.lower()


def needs(evt: Dict[str, Any]) -> Dict[str, int]:
    return {commodity_key(r["Name"]): r["RequiredAmount"] - r["ProvidedAmount"]
            for r in evt.get("ResourcesRequired", []) if r["RequiredAmount"] > 0}


def needs_payload(evt: Dict[str, Any], build_id: str) -> Dict[str, Any]:
    return {"buildId": build_id, "commodities": needs(evt),
            "maxNeed": sum(r["RequiredAmount"] for r in evt.get("ResourcesRequired", [])),
            "colonisationConstructionDepot": evt}


def contribution_payload(evt: Dict[str, Any]) -> Dict[str, int]:
    return {commodity_key(c["Name"]): c["Amount"] for c in evt.get("Contributions", []) if c["Amount"] > 0}


def check_key(key: str) -> Optional[str]:
    """Commander name the key belongs to, or None. Synchronous."""
    try:
        resp = requests.get(f"{_BASE_URL}/api/cmdr/", headers={"User-Agent": USER_AGENT, "rcc-key": key},
                            timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        body = resp.json()
        return (body.get("displayName") or None) if isinstance(body, dict) else None
    except (requests.RequestException, ValueError) as exc:
        log.warning("Raven Colonial key check failed: %s", type(exc).__name__)
        return None


class RavenColonialPusher:
    def __init__(self, key: str, cmdr: str, on_status: Callable[[str], None]):
        self._key = key
        self._cmdr = cmdr
        self._on_status = on_status
        self._builds: Dict[Any, Dict[str, Any]] = {}
        self._misses: Dict[Any, float] = {}   # failed/404 lookups: retry time
        self._last_needs: Dict[str, Dict[str, int]] = {}
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="RavenColonialPusher", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def submit(self, evt: Dict[str, Any], system_address: int) -> None:
        if evt.get("event") not in _EVENTS:
            return
        try:
            self._queue.put_nowait((evt, system_address))
        except queue.Full:
            log.warning("Raven Colonial queue full — dropping %s", evt.get("event"))

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._handle(*item)

    def _handle(self, evt: Dict[str, Any], system_address: int) -> None:
        try:
            cache_key = (system_address, evt.get("MarketID"))
            project = self._builds.get(cache_key)
            if project is None and self._misses.get(cache_key, 0) <= _clock():
                project = get_project_for_station(*cache_key)
                if project is None:
                    self._misses[cache_key] = _clock() + _MISS_TTL
                else:
                    self._builds[cache_key] = project
            if project is None:
                self._on_status("Build not on Raven Colonial")
                return
            build_id = project["buildId"]
            if evt["event"] == "ColonisationConstructionDepot":
                current = needs(evt)
                if current == self._last_needs.setdefault(build_id, project.get("commodities") or {}):
                    return
                if self._post(f"/api/project/{build_id}", needs_payload(evt, build_id)):
                    self._last_needs[build_id] = current
            else:
                self._post(f"/api/project/{build_id}/contribute/{quote(self._cmdr)}", contribution_payload(evt))
        except Exception as exc:
            # exception text may echo request details; log the type only
            log.warning("Raven Colonial send failed: %s", type(exc).__name__)
            self._on_status("Raven Colonial: send failed")

    def _post(self, path: str, body: Dict[str, Any]) -> bool:
        resp = requests.post(f"{_BASE_URL}{path}", json=body, timeout=_TIMEOUT,
                             headers={"User-Agent": USER_AGENT, "rcc-key": self._key})
        if resp.status_code >= 400:
            log.warning("Raven Colonial send failed: status %s", resp.status_code)
            self._on_status("Raven Colonial: send failed")
            return False
        return True
