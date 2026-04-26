"""Spansh API client for PowerPlay system search."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple

import requests

log = logging.getLogger(__name__)

_SEARCH_URL = "https://spansh.co.uk/api/systems/search"
_TIMEOUT    = 15


@dataclass
class SpanshSystem:
    name:              str
    distance:          float
    controlling_power: str
    pp_state:          str
    powers:            List[str] = field(default_factory=list)
    station_types:     List[str] = field(default_factory=list)

    def all_powers(self) -> List[str]:
        """Deduplicated list: controlling power first, then any additional powers."""
        seen: set = set()
        result: List[str] = []
        for p in ([self.controlling_power] + self.powers):
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def has_megaship(self) -> bool:
        return any("megaship" in t.lower() for t in self.station_types)

    def has_settlement(self) -> bool:
        return any("settlement" in t.lower() for t in self.station_types)

    def has_starport(self) -> bool:
        return any(
            kw in t.lower()
            for t in self.station_types
            for kw in ("starport", "coriolis", "orbis", "ocellus")
        )

    def facility_summary(self) -> str:
        tags = []
        if self.has_megaship():
            tags.append("Megaship")
        if self.has_settlement():
            tags.append("Settlement")
        if self.has_starport():
            tags.append("Starport")
        if not tags:
            tags.append("Outpost" if self.station_types else "—")
        return ", ".join(tags)


class SpanshClient:
    """
    Thin wrapper around the Spansh system-search API.

    All methods are synchronous — call from a worker thread, never the UI thread.
    """

    def search_pp_systems(
        self,
        power:    str,
        mission:  str,   # "reinforcement" | "undermining" | "acquisition" | "all"
        ref_x:    float,
        ref_y:    float,
        ref_z:    float,
        range_ly: int = 100,
        facility: str = "any",   # "any" | "megaship" | "settlement"
        size:     int = 50,
    ) -> Tuple[List[SpanshSystem], str]:
        """
        Returns (results, error).  error is "" on success.
        Results are sorted by distance ascending, already filtered to range_ly.
        """
        filters: dict = {}

        if mission == "reinforcement":
            filters["controlling_power"] = {"value": power, "comparison": "="}
        # acquisition, undermining, all — no server-side power filter; post-filter below

        body = {
            "filters":          filters,
            "reference_coords": {"x": ref_x, "y": ref_y, "z": ref_z},
            "sort":             [{"distance": {"direction": "asc"}}],
            "size":             size,
            "page":             0,
        }

        try:
            resp = requests.post(_SEARCH_URL, json=body, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Spansh request failed: %s", exc)
            return [], str(exc)
        except ValueError:
            log.error("Spansh returned non-JSON response")
            return [], "Invalid response from Spansh"

        raw_results = data.get("results") or []
        if not isinstance(raw_results, list):
            log.warning("Unexpected Spansh response shape: %s", list(data.keys()))
            return [], f"Unexpected response shape. Keys: {list(data.keys())}"

        out: List[SpanshSystem] = []
        for sys in raw_results:
            if not isinstance(sys, dict):
                continue

            name       = sys.get("name") or ""
            dist       = sys.get("distance") or 0.0
            ctrl_power = sys.get("controlling_power") or ""
            pp_state   = sys.get("power_state") or ""
            raw_powers = sys.get("power") or []
            powers     = [str(p) for p in raw_powers if p] if isinstance(raw_powers, list) else []

            # Distance guard
            try:
                dist = float(dist)
            except (TypeError, ValueError):
                dist = 0.0
            if dist > range_ly:
                continue

            # Mission post-filters
            if mission == "reinforcement" and not ctrl_power:
                continue
            if mission == "undermining":
                if not ctrl_power or ctrl_power == power:
                    continue
            if mission == "acquisition":
                state_lower = pp_state.lower()
                is_acq = (not ctrl_power) or (state_lower in ["uncontrolled", "expansion", "contested"])
                if not is_acq:
                    continue

            station_types = [
                s.get("type") or ""
                for s in (sys.get("stations") or [])
                if isinstance(s, dict) and s.get("type")
            ]

            # Facility filter
            candidate = SpanshSystem(
                name=name,
                distance=dist,
                controlling_power=ctrl_power,
                pp_state=pp_state,
                powers=powers,
                station_types=station_types,
            )
            if facility == "megaship"   and not candidate.has_megaship():
                continue
            if facility == "settlement" and not candidate.has_settlement():
                continue

            out.append(candidate)

        return out, ""
