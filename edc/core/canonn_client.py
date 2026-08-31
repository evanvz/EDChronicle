"""Canonn Research API client — community-sourced POI, codex, and signal
intel for the current system, plus the nearest unclaimed codex challenge.

All methods are synchronous — call from a worker thread, never the UI thread.
Read-only queries against Canonn's public Cloud Functions API; EDChronicle
does not submit anything to Canonn (unlike EDDN, where we do contribute).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import requests

log = logging.getLogger(__name__)

_POI_URL = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/getSystemPoi"
_CHALLENGE_URL = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/challenge/next"
_COMPRES_URL = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/get_compres"
_TIMEOUT = 20


@dataclass
class CodexEntry:
    name: str
    category: str
    body: str = ""
    scanned: bool = False


@dataclass
class SystemPoi:
    system: str
    codex: List[CodexEntry] = field(default_factory=list)
    saa_signals: List[Dict[str, Any]] = field(default_factory=list)

    def unclaimed_codex(self) -> List[CodexEntry]:
        return [c for c in self.codex if not c.scanned]


class CanonnClient:

    def get_system_poi(self, system: str, odyssey: bool, cmdr: str) -> Tuple[SystemPoi, str]:
        """Returns (poi, error). error is "" on success."""
        if not system:
            return SystemPoi(system=system), "No system name"

        params = {
            "system": system,
            "odyssey": "Y" if odyssey else "N",
            "cmdr": cmdr or "",
        }
        try:
            resp = requests.get(_POI_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Canonn getSystemPoi failed: %s", exc)
            return SystemPoi(system=system), str(exc)
        except ValueError:
            return SystemPoi(system=system), "Invalid response from Canonn"

        if not isinstance(data, dict):
            return SystemPoi(system=system), "Unexpected response shape"

        codex_entries: List[CodexEntry] = []
        for rec in (data.get("codex") or []):
            if not isinstance(rec, dict):
                continue
            name = rec.get("english_name") or ""
            if not name:
                continue
            scanned_raw = rec.get("scanned")
            scanned = scanned_raw is True or str(scanned_raw).strip().lower() == "true"
            codex_entries.append(CodexEntry(
                name=name,
                category=rec.get("hud_category") or "",
                body=rec.get("body") or "",
                scanned=scanned,
            ))

        saa = [s for s in (data.get("SAAsignals") or []) if isinstance(s, dict)]

        return SystemPoi(system=system, codex=codex_entries, saa_signals=saa), ""

    def get_nearest_challenge(self, cmdr: str, x: float, y: float, z: float) -> Tuple[Dict[str, Any], str]:
        """Returns ({system, english_name, distance}, error). error is "" on success."""
        if not cmdr:
            return {}, "No commander name"

        params = {"cmdr": cmdr, "x": x, "y": y, "z": z}
        try:
            resp = requests.get(_CHALLENGE_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Canonn challenge/next failed: %s", exc)
            return {}, str(exc)
        except ValueError:
            return {}, "Invalid response from Canonn"

        if not isinstance(data, dict):
            return {}, "Unexpected response shape"

        return data, ""

    def get_compres(self, systems: List[str]) -> Tuple[Dict[str, List[str]], str]:
        """Crowdsourced Resource Extraction Site [High]/[Hazardous] and
        Compromised Nav Beacon presence per system name. Returns
        ({system_name: [interesting, ...]}, error) -- error is "" on
        success. Response confirmed live: a flat JSON array of
        {"system": ..., "interesting": ...} pairs, one per known site."""
        if not systems:
            return {}, "No systems given"

        params = {"systems": ",".join(systems)}
        try:
            resp = requests.get(_COMPRES_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Canonn get_compres failed: %s", exc)
            return {}, str(exc)
        except ValueError:
            return {}, "Invalid response from Canonn"

        if not isinstance(data, list):
            return {}, "Unexpected response shape"

        by_system: Dict[str, List[str]] = {}
        for rec in data:
            if not isinstance(rec, dict):
                continue
            system = rec.get("system")
            interesting = rec.get("interesting")
            if isinstance(system, str) and isinstance(interesting, str):
                by_system.setdefault(system, []).append(interesting)

        return by_system, ""
