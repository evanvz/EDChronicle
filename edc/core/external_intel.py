import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("settings.external_intel")

class ExternalIntel:
    """
    Offline, advisory-only POI store.

    File location (portable-in-repo):
      <settings_dir>/external_pois.json
    """

    def __init__(self, settings_dir: Path, filename: str = "external_pois.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self._systems: Dict[str, List[Dict[str, Any]]] = {}
        self._addresses: Dict[str, List[Dict[str, Any]]] = {}
        self._load(force=True)

    def _k(self, system_name: str) -> str:
        return (system_name or "").strip().lower()

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._systems = {}
                self._addresses = {}
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            systems = {}
            addrs = {}
            if isinstance(data, dict):
                systems = data.get("systems") or {}
                addrs = data.get("system_addresses") or {}

            # Normalize system keys for case-insensitive matching
            norm_systems: Dict[str, Any] = {}
            if isinstance(systems, dict):
                for k, v in systems.items():
                    if not isinstance(k, str):
                        continue
                    nk = self._k(k)
                    if not nk:
                        continue
                    # Merge lists if duplicates exist under different casing
                    if nk in norm_systems and isinstance(norm_systems[nk], list) and isinstance(v, list):
                        norm_systems[nk].extend(v)
                    else:
                        norm_systems[nk] = v

            self._systems = norm_systems
            self._addresses = addrs if isinstance(addrs, dict) else {}

        except Exception:
            log.exception("Failed to load external_pois.json")
            self._systems = {}
            self._addresses = {}
            self._mtime = None

    def get_pois(self, system_name: str, system_address: Optional[int] = None) -> List[Dict[str, Any]]:
        # Reload if the file changed
        self._load(force=False)

        out: List[Dict[str, Any]] = []
        try:
            if isinstance(system_address, int):
                recs = self._addresses.get(str(system_address)) or []
                if isinstance(recs, list):
                    out.extend([r for r in recs if isinstance(r, dict)])

            key = self._k(system_name)
            recs2 = self._systems.get(key) or []
            if isinstance(recs2, list):
                out.extend([r for r in recs2 if isinstance(r, dict)])
        except Exception:
            pass

        return out
