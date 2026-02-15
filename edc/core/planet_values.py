import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("edc.planet_values")

from edc.utils.normalization import _norm


@dataclass(frozen=True)
class PlanetValueRow:
    planet_type: str
    terraformable: bool
    fss: Optional[int]
    fss_dss: Optional[int]
    fss_fd: Optional[int]
    fss_fd_dss: Optional[int]

class PlanetValueTable:
    def estimate_base_value(self, event: Dict[str, Any]) -> Optional[int]:
        planet_class = event.get("PlanetClass")
        terraformable = event.get("Terraformable", False)

        pt = self._canonical_type(planet_class)
        if not pt:
            return None

        row = self._rows.get((pt, terraformable))
        if not row:
            return None

        return row.fss
    """
    Uses planet_values.json as an estimator table.
    We normalize journal PlanetClass strings to match rows.
    """

    def __init__(self, rows: Dict[Tuple[str, bool], PlanetValueRow]):
        self._rows = rows
        # Build a normalization map from the actual planet_types present in the JSON.
        self._type_norm_map: Dict[str, str] = {}
        for (planet_type, _tf) in rows.keys():
            self._type_norm_map[_norm(planet_type)] = planet_type

    @staticmethod
    def load_from_paths(*paths: Path) -> Optional["PlanetValueTable"]:
        for p in paths:
            try:
                if p and p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    rows_in = data.get("entries") or data.get("rows") or []
                    rows: Dict[Tuple[str, bool], PlanetValueRow] = {}
                    for r in rows_in:
                        pt = r.get("planet_type")
                        tf = r.get("terraformable")
                        # Skip junk/placeholder rows
                        if not isinstance(pt, str) or not isinstance(tf, bool):
                            continue
                        v = r.get("values") or {}
                        row = PlanetValueRow(
                            planet_type=pt,
                            terraformable=tf,
                            fss=v.get("fss", r.get("fss")),
                            fss_dss=v.get("fss_dss", r.get("fss_dss")),
                            fss_fd=v.get("fss_fd", r.get("fss_fd")),
                            fss_fd_dss=v.get("fss_fd_dss", r.get("fss_fd_dss")),
                        )
                        rows[(pt, tf)] = row
                    if rows:
                        log.info("Loaded planet values from %s (%d rows)", p, len(rows))
                        return PlanetValueTable(rows)
            except Exception:
                log.exception("Failed to load planet values from %s", p)
        return None

    def _canonical_type(self, planet_class: str) -> Optional[str]:
        if not planet_class:
            return None
        key = _norm(planet_class)
        # Direct match against known types
        if key in self._type_norm_map:
            return self._type_norm_map[key]

        # Common journal → table name fixups (safe guesses)
        aliases = {
            _norm("High metal content world"): _norm("High Metal Content Planet"),
            _norm("High metal content body"): _norm("High Metal Content Planet"),
            _norm("Rocky body"): _norm("Rocky Body"),
            _norm("Icy body"): _norm("Icy Body"),
            _norm("Metal rich body"): _norm("Metal Rich Body"),
            _norm("Water world"): _norm("Water World"),
            _norm("Earthlike world"): _norm("Earth-Like World"),
            _norm("Ammonia world"): _norm("Ammonia World"),
            _norm("Gas giant with water based life"): _norm("Gas Giant With Water Based Life"),
            _norm("Gas giant with ammonia based life"): _norm("Gas Giant With Ammonia Based Life"),
        }
        ali = aliases.get(key)
        if ali and ali in self._type_norm_map:
            return self._type_norm_map[ali]

        return None

    def estimate(
        self,
        planet_class: str,
        terraformable: bool,
        mapped: bool,
        first_discovered: bool,
    ) -> Optional[int]:
        pt = self._canonical_type(planet_class)
        if not pt:
            return None
        row = self._rows.get((pt, terraformable))
        if not row:
            return None

        if first_discovered and mapped:
            return row.fss_fd_dss
        if first_discovered and not mapped:
            return row.fss_fd
        if (not first_discovered) and mapped:
            return row.fss_dss
        return row.fss
