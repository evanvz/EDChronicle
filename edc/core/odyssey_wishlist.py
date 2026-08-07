import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("edc.odyssey_wishlist")

_VALID_KINDS = {"suit_grade", "weapon_grade", "suit_module", "weapon_module"}


class OdysseyWishlist:
    """
    Persists tracked Odyssey (on-foot) suit/weapon engineering targets.

    File location:
      <data_dir>/odyssey_engineering_wishlist.json

    Format:
      {"items": [
        {"kind": "suit_grade", "name": "Maverick", "grade": 3},
        {"kind": "weapon_module", "name": "scope"}
      ]}
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                return []
            out = []
            for rec in items:
                if not isinstance(rec, dict) or rec.get("kind") not in _VALID_KINDS:
                    continue
                name = rec.get("name")
                if not isinstance(name, str) or not name:
                    continue
                entry = {"kind": rec["kind"], "name": name}
                if rec["kind"] in ("suit_grade", "weapon_grade"):
                    grade = rec.get("grade")
                    if not isinstance(grade, int):
                        continue
                    entry["grade"] = grade
                out.append(entry)
            return out
        except Exception:
            log.exception("Failed to load odyssey_engineering_wishlist.json")
            return []

    def save(self, items: List[Dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"items": items}
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            log.exception("Failed to save odyssey_engineering_wishlist.json")
