import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("edc.engineering_wishlist")


class EngineeringWishlist:
    """
    Persists the user's selected blueprint+grade build targets.

    File location:
      <data_dir>/engineering_wishlist.json

    Format:
      {"items": [{"fdname": "FSD_LongRange", "grade": 5, "experimental": null}, ...]}

    "experimental" is the edname of an optional Experimental Effect
    (see experimental_effects.py), or null/absent for none.
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
                if not isinstance(rec, dict):
                    continue
                fdname = rec.get("fdname")
                grade = rec.get("grade")
                experimental = rec.get("experimental")
                if isinstance(fdname, str) and fdname and isinstance(grade, int):
                    out.append({
                        "fdname": fdname,
                        "grade": grade,
                        "experimental": experimental if isinstance(experimental, str) else None,
                    })
            return out
        except Exception:
            log.exception("Failed to load engineering_wishlist.json")
            return []

    def save(self, items: List[Dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "items": [
                    {
                        "fdname": it["fdname"],
                        "grade": it["grade"],
                        "experimental": it.get("experimental"),
                    }
                    for it in items
                    if isinstance(it, dict) and isinstance(it.get("fdname"), str) and isinstance(it.get("grade"), int)
                ]
            }
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            log.exception("Failed to save engineering_wishlist.json")
