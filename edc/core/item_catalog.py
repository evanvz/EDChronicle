import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.item_catalog")


class ItemCatalog:
    """
    Offline, advisory-only metadata catalog for Materials (raw/manufactured/encoded)
    and Odyssey ShipLocker items (goods/data/assets).

    File location (portable-in-repo):
      <settings_dir>/inara_items_catalog.json

    Expected format (minimal):
      {
        "last_updated": "YYYY-MM-DD",
        "items": [
          {
            "name": "Pharmaceutical Isolators",
            "type": "Manufactured",
            "subtype": "Chemical",
            "grade": "Very rare",
            "locations": ["USS (High grade emissions)", "Mission reward"]
          },
          {
            "name": "Manufacturing Instructions",
            "type": "Data",
            "subtype": "Odyssey",
            "locations": ["IND buildings", "RES buildings", "Mission reward"]
          }
        ]
      }
    """

    def __init__(self, settings_dir: Path, filename: str = "inara_items_catalog.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None

        self._by_name: Dict[str, Dict[str, Any]] = {}
        self._count: int = 0

        self._load(force=True)

    def _norm(self, v: Any) -> str:
        if not isinstance(v, str):
            return ""
        try:
            return " ".join(v.split()).strip()
        except Exception:
            return v.strip()

    def _key(self, name: Any) -> str:
        return self._norm(name).lower()

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._by_name = {}
                self._count = 0
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = None
            items = []
            if isinstance(data, dict):
                lu = data.get("last_updated")
                self.last_updated = self._norm(lu) or None
                items = data.get("items") or []

            by_name: Dict[str, Dict[str, Any]] = {}
            count = 0

            if isinstance(items, list):
                for rec in items:
                    if not isinstance(rec, dict):
                        continue
                    name = self._norm(rec.get("name"))
                    if not name:
                        continue
                    k = self._key(name)
                    out = dict(rec)
                    out["name"] = name
                    # Normalize common fields for UI
                    for f in ("type", "subtype", "grade"):
                        if f in out:
                            out[f] = self._norm(out.get(f))
                    locs = out.get("locations")
                    if isinstance(locs, list):
                        out["locations"] = [self._norm(x) for x in locs if self._norm(x)]
                    elif isinstance(locs, str):
                        s = self._norm(locs)
                        out["locations"] = [s] if s else []
                    else:
                        out["locations"] = []

                    by_name[k] = out
                    count += 1

            self._by_name = by_name
            self._count = count
        except Exception:
            log.exception("Failed to load inara_items_catalog.json")
            self._by_name = {}
            self._count = 0
            self.last_updated = None
            self._mtime = None

    def has_data(self) -> bool:
        self._load(force=False)
        return self._count > 0

    def count(self) -> int:
        self._load(force=False)
        return int(self._count)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        self._load(force=False)
        k = self._key(name)
        if not k:
            return None
        rec = self._by_name.get(k)
        return rec if isinstance(rec, dict) else None

    def get_subtype_label(self, name: str) -> str:
        """
        Returns a compact label for table display, e.g.:
          "Manufactured / Chemical"
          "Raw / Raw material 1"
          "Data / Odyssey"
        """
        rec = self.get(name)
        if not rec:
            return ""
        t = self._norm(rec.get("type"))
        st = self._norm(rec.get("subtype"))
        if t and st:
            return f"{t} / {st}"
        return t or st or ""
