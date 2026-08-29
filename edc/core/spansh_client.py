"""Spansh API client for PowerPlay system search."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

_SEARCH_URL        = "https://spansh.co.uk/api/systems/search"
_BODIES_SEARCH_URL = "https://spansh.co.uk/api/bodies/search"
_TIMEOUT    = 15
_BODIES_TIMEOUT = 30

# Best mining reserve tiers, worth prioritising over Common/Low/Depleted.
_GOOD_RESERVE_LEVELS = ["Pristine", "Major"]


@dataclass
class MiningRingResult:
    system_name:   str
    body_name:     str
    ring_name:     str
    ring_type:     str
    reserve_level: str
    distance:      float
    material:      str
    hotspot_count: int


@dataclass
class SpanshSystem:
    name:              str
    distance:          float
    controlling_power: str
    pp_state:          str
    powers:            List[str] = field(default_factory=list)
    station_types:     List[str] = field(default_factory=list)
    id64:              Optional[int] = None

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
        mission:  str,    # "reinforcement" | "undermining" | "acquisition" | "all"
        ref_x:    float,
        ref_y:    float,
        ref_z:    float,
        range_ly: int = 100,
        facility: str = "any",    # "any" | "megaship" | "settlement"
        pp_state: str = "any",    # "any" | "stronghold" | "fortified" | "exploited" | "expansion" | "contested" | "uncontrolled"
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
            sys_state  = sys.get("power_state") or ""
            raw_powers = sys.get("power") or []
            powers     = [str(p) for p in raw_powers if p] if isinstance(raw_powers, list) else []
            id64       = sys.get("id64") if isinstance(sys.get("id64"), int) else None

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
                state_lower = sys_state.lower()
                # Expansion state where another power is controlling = their expansion, not ours
                if state_lower == "expansion" and ctrl_power and ctrl_power != power:
                    continue
                is_acq = (not ctrl_power) or (state_lower in ["uncontrolled", "expansion", "contested"])
                if not is_acq:
                    continue

            station_types = [
                s.get("type") or ""
                for s in (sys.get("stations") or [])
                if isinstance(s, dict) and s.get("type")
            ]

            # PP state filter
            if pp_state != "any" and sys_state.lower() != pp_state.lower():
                continue

            # Facility filter
            candidate = SpanshSystem(
                name=name,
                distance=dist,
                controlling_power=ctrl_power,
                pp_state=sys_state,
                powers=powers,
                station_types=station_types,
                id64=id64,
            )
            if facility == "megaship"   and not candidate.has_megaship():
                continue
            if facility == "settlement" and not candidate.has_settlement():
                continue

            out.append(candidate)

        return out, ""

    def fetch_system_bodies(self, system_name: str, system_address: int | None = None) -> Tuple[List[dict], str]:
        """
        Returns (body_list, error).  Each body dict has:
          name, planet_class, distance_ls, estimated_value, landable (int|None),
          plus physical stats.
        Uses id64 filter when system_address is provided (exact match); falls back to name search.
        """
        if isinstance(system_address, int):
            filters = {"id64": {"value": system_address, "comparison": "="}}
        else:
            filters = {"name": {"value": system_name, "comparison": "="}}

        body = {
            "filters": filters,
            "sort":    [{"distance": {"direction": "asc"}}],
            "size":    1,
            "page":    0,
        }
        try:
            resp = requests.post(_SEARCH_URL, json=body, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Spansh body fetch failed: %s", exc)
            return [], str(exc)
        except ValueError:
            return [], "Invalid response from Spansh"

        results = data.get("results") or []
        if not results:
            return [], f"System not found on Spansh: {system_name!r}"

        sys_data = results[0]

        raw_bodies = sys_data.get("bodies") or []

        out: List[dict] = []
        for b in raw_bodies:
            if not isinstance(b, dict):
                continue
            name = b.get("name") or ""
            if not name:
                continue
            planet_class = b.get("subtype") or ""
            distance_ls  = b.get("distance_to_arrival") or 0.0
            est_value    = b.get("estimated_mapping_value") or b.get("estimated_scan_value") or 0
            landmarks    = b.get("landmarks") or []
            landable: int | None = None
            if b.get("type") == "Planet":
                landable = 1 if landmarks else 0
            try:
                distance_ls = float(distance_ls)
            except (TypeError, ValueError):
                distance_ls = 0.0

            # Physical stats — convert Spansh units to journal-compatible units
            # gravity: Spansh stores in G → journal stores in m/s²
            _g = b.get("gravity")
            gravity_ms2 = float(_g) * 9.80665 if isinstance(_g, (int, float)) else None
            # radius: Spansh stores in km → journal stores in m
            _r = b.get("radius")
            radius_m = float(_r) * 1000.0 if isinstance(_r, (int, float)) else None
            _em = b.get("earth_masses")
            mass_em = float(_em) if isinstance(_em, (int, float)) else None
            _t = b.get("surface_temperature")
            surface_temperature = float(_t) if isinstance(_t, (int, float)) else None
            # surface_pressure: Spansh stores in Pa (same as journal)
            _p = b.get("surface_pressure")
            surface_pressure = float(_p) if isinstance(_p, (int, float)) else None
            atmosphere_type = b.get("atmosphere_type") or None
            volcanism = b.get("volcanism_type") or None
            _tl = b.get("is_rotational_period_tidally_locked")
            tidal_lock = int(bool(_tl)) if isinstance(_tl, bool) else None

            out.append({
                "name":               name,
                "planet_class":       planet_class,
                "distance_ls":        distance_ls,
                "estimated_value":    int(est_value),
                "landable":           landable,
                "surface_gravity":    gravity_ms2,
                "radius":             radius_m,
                "mass_em":            mass_em,
                "surface_temperature": surface_temperature,
                "surface_pressure":   surface_pressure,
                "atmosphere_type":    atmosphere_type,
                "volcanism":          volcanism,
                "tidal_lock":         tidal_lock,
            })

        return out, ""

    def search_mining_rings(
        self,
        material: str,
        ref_x: float,
        ref_y: float,
        ref_z: float,
        range_ly: int = 100,
        reserve_levels: List[str] | None = None,
        candidate_size: int = 500,
    ) -> Tuple[List["MiningRingResult"], str]:
        """
        Finds rings containing a hotspot for `material`, sorted by distance.

        Spansh's bodies/search does not appear to support server-side
        filtering by ring hotspot material (extensively tested — every
        filter shape tried returns an unfiltered/capped result). This
        works around that by server-side filtering on reserve_level
        (confirmed working) sorted by distance, fetching up to
        `candidate_size` candidates, then matching the material client-side.

        Limitation: only the closest `candidate_size` good-reserve ring
        bodies are scanned, so a rare material near the edge of a large
        range_ly could be missed if it falls outside that window.

        Returns (results, error). error is "" on success.
        """
        levels = reserve_levels if reserve_levels else _GOOD_RESERVE_LEVELS
        body = {
            "filters":          {"reserve_level": {"value": levels}},
            "reference_coords": {"x": ref_x, "y": ref_y, "z": ref_z},
            "sort":             [{"distance": {"direction": "asc"}}],
            "size":             candidate_size,
            "page":             0,
        }
        try:
            resp = requests.post(_BODIES_SEARCH_URL, json=body, timeout=_BODIES_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Spansh mining ring search failed: %s", exc)
            return [], str(exc)
        except ValueError:
            return [], "Invalid response from Spansh"

        raw_results = data.get("results") or []
        if not isinstance(raw_results, list):
            return [], f"Unexpected response shape. Keys: {list(data.keys())}"

        material_lower = material.strip().lower()
        out: List[MiningRingResult] = []
        for rec in raw_results:
            if not isinstance(rec, dict):
                continue
            dist = rec.get("distance")
            try:
                dist = float(dist)
            except (TypeError, ValueError):
                dist = 0.0
            if dist > range_ly:
                continue

            rings = rec.get("rings")
            if not isinstance(rings, list):
                continue
            for ring in rings:
                if not isinstance(ring, dict):
                    continue
                signals = ring.get("signals")
                if not isinstance(signals, list):
                    continue
                for sig in signals:
                    if not isinstance(sig, dict):
                        continue
                    sig_name = str(sig.get("name") or "")
                    if sig_name.strip().lower() != material_lower:
                        continue
                    out.append(MiningRingResult(
                        system_name=str(rec.get("system_name") or ""),
                        body_name=str(rec.get("name") or ""),
                        ring_name=str(ring.get("name") or ""),
                        ring_type=str(ring.get("type") or ""),
                        reserve_level=str(rec.get("reserve_level") or ""),
                        distance=dist,
                        material=sig_name,
                        hotspot_count=int(sig.get("count") or 0),
                    ))

        out.sort(key=lambda r: r.distance)
        return out, ""

    def fetch_system_rings(self, system_address: int) -> Tuple[List[dict], str]:
        """
        Every ring in this system that Spansh knows about, with whatever
        community-reported hotspot signals it has (empty list if none — a
        genuine "nobody has DSS'd this and had it reach Spansh via EDDN" gap,
        distinct from this commander simply not having scanned it personally).

        Each entry: {"ring_name", "parent_body", "ring_type", "signals": [{"name","count"}, ...]}.
        Returns (rings, error). error is "" on success.
        """
        body = {
            "filters": {"system_id64": {"value": system_address, "comparison": "="}},
            "size":    500,
            "page":    0,
        }
        try:
            resp = requests.post(_BODIES_SEARCH_URL, json=body, timeout=_BODIES_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.error("Spansh ring fetch failed: %s", exc)
            return [], str(exc)
        except ValueError:
            return [], "Invalid response from Spansh"

        out: List[dict] = []
        for rec in (data.get("results") or []):
            if not isinstance(rec, dict):
                continue
            for ring in (rec.get("rings") or []):
                if not isinstance(ring, dict):
                    continue
                signals = []
                for sig in (ring.get("signals") or []):
                    if isinstance(sig, dict) and sig.get("name"):
                        signals.append({"name": str(sig.get("name")), "count": int(sig.get("count") or 0)})
                out.append({
                    "ring_name":   str(ring.get("name") or ""),
                    "parent_body": str(rec.get("name") or ""),
                    "ring_type":   str(ring.get("type") or ""),
                    "signals":     signals,
                })
        return out, ""
