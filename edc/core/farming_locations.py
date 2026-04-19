import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.farming_locations")


class FarmingLocations:
    """
    Offline, advisory-only farming location store.

    File location (portable-in-repo):
      <settings_dir>/elite_farming_locations.json

    Data model (expected):
      {
        "last_updated": "YYYY-MM-DD",
        "farming_locations": {
          "encoded": [ { ... } ],
          "raw": [ { ... } ],
          "manufactured": [ { ... } ],
          "odyssey_onfoot": [ { ... } ],
          "guardian": [ { ... } ],
          "thargoid": [ { ... } ]
        },
        "bgs_tips": { ... }
      }
    """

    def __init__(self, settings_dir: Path, filename: str = "elite_farming_locations.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None

        # Flattened records (each is dict)
        self._records: List[Dict[str, Any]] = []
        # Indexes
        self._by_system: Dict[str, List[Dict[str, Any]]] = {}
        self._by_material: Dict[str, List[Dict[str, Any]]] = {}

        # Advisory tips (pass-through)
        self.bgs_tips: Dict[str, Any] = {}

        self._load(force=True)

    def _norm(self, v: Any) -> str:
        if not isinstance(v, str):
            return ""
        try:
            return " ".join(v.split()).strip()
        except Exception:
            return v.strip()

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._records = []
                self._by_system = {}
                self._by_material = {}
                self.bgs_tips = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = None
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = self._norm(lu) or None

            farming = {}
            tips = {}
            if isinstance(data, dict):
                farming = data.get("farming_locations") or {}
                tips = data.get("bgs_tips") or {}

            self.bgs_tips = tips if isinstance(tips, dict) else {}

            records: List[Dict[str, Any]] = []
            by_system: Dict[str, List[Dict[str, Any]]] = {}
            by_material: Dict[str, List[Dict[str, Any]]] = {}

            if isinstance(farming, dict):
                for domain, arr in farming.items():
                    if not isinstance(arr, list):
                        continue
                    dom = self._norm(domain).lower() or "other"
                    for rec in arr:
                        if not isinstance(rec, dict):
                            continue
                        # Normalize core fields
                        name = self._norm(rec.get("name")) or "Farm Site"
                        system = self._norm(rec.get("system"))
                        body = self._norm(rec.get("body"))
                        method = self._norm(rec.get("method"))
                        mats = rec.get("key_materials") or rec.get("materials") or rec.get("mats") or []
                        if not isinstance(mats, list):
                            mats = []
                        mats_clean = []
                        for x in mats:
                            s = self._norm(x)
                            if s:
                                mats_clean.append(s)

                        out = dict(rec)
                        out["domain"] = dom
                        out["name"] = name
                        if system:
                            out["system"] = system
                        if body:
                            out["body"] = body
                        if method:
                            out["method"] = method
                        out["key_materials"] = mats_clean

                        records.append(out)

                        if system:
                            sk = system.lower()
                            by_system.setdefault(sk, []).append(out)

                        for mat in mats_clean:
                            mk = mat.lower()
                            by_material.setdefault(mk, []).append(out)

                        # Also index site-level materials (e.g. raw crystalline shard sites)
                        for site in (rec.get("sites") or []):
                            if not isinstance(site, dict):
                                continue
                            for mat in (site.get("materials") or []):
                                ms = self._norm(mat)
                                if ms:
                                    mk = ms.lower()
                                    if out not in by_material.get(mk, []):
                                        by_material.setdefault(mk, []).append(out)

            self._records = records
            self._by_system = by_system
            self._by_material = by_material
        except Exception:
            log.exception("Failed to load elite_farming_locations.json")
            self._records = []
            self._by_system = {}
            self._by_material = {}
            self.bgs_tips = {}
            self.last_updated = None
            self._mtime = None

    def get_for_system(self, system_name: str) -> List[Dict[str, Any]]:
        self._load(force=False)
        sk = self._norm(system_name).lower()
        if not sk:
            return []
        recs = self._by_system.get(sk) or []
        return [r for r in recs if isinstance(r, dict)]

    def get_for_material(self, material_name: str) -> List[Dict[str, Any]]:
        self._load(force=False)
        mk = self._norm(material_name).lower()
        if not mk:
            return []
        recs = self._by_material.get(mk) or []
        return [r for r in recs if isinstance(r, dict)]

    def get_for_materials(self, material_names: list) -> List[Dict[str, Any]]:
        """Return deduped farming entries that match any of the given material names."""
        self._load(force=False)
        seen: set = set()
        result: List[Dict[str, Any]] = []
        for name in material_names:
            mk = self._norm(name).lower()
            if not mk:
                continue
            for rec in (self._by_material.get(mk) or []):
                rid = id(rec)
                if rid not in seen:
                    seen.add(rid)
                    result.append(rec)
        return result

    def has_data(self) -> bool:
        self._load(force=False)
        return bool(self._records)
