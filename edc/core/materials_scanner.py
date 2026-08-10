"""One-shot scan to reconstruct current Raw/Manufactured/Encoded material
counts at app startup.

The "Materials" event is a full absolute snapshot, but only fires at
journal-file start (commander login) or when the player opens the in-game
Materials panel — the app's live bootstrap only re-reads the tail of the
current journal (see journal_watcher.py::_bootstrap_newest_system), which
can miss it on a long session, leaving state.materials_raw/manufactured/
encoded empty. Same reasoning as notoriety_scanner.py/rank_scanner.py/
carrier_scanner.py.

Finds the most recent Materials snapshot (newest file first, cheap — it
fires often), then replays MaterialCollected/MaterialDiscarded/
MaterialTrade/EngineerCraft deltas from right after that point forward,
exactly like event_engine.py's own live handling, so counts are correct
even if the player picked up/spent materials between that snapshot and
the app restart.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

_CATEGORY_FIELDS = {"Raw": "raw", "Manufactured": "manufactured", "Encoded": "encoded"}


def _apply_snapshot(event: dict, by_category: Dict[str, Dict[str, int]]) -> None:
    for d in by_category.values():
        d.clear()
    for field, cat_key in _CATEGORY_FIELDS.items():
        for rec in event.get(field) or []:
            name = (rec.get("Name") or "").strip().lower()
            count = rec.get("Count")
            if name and isinstance(count, int):
                by_category[cat_key][name] = count


def _adjust(by_category: Dict[str, Dict[str, int]], category: Optional[str], name: Optional[str], delta: int) -> None:
    name = (name or "").strip().lower()
    if not name:
        return
    if category:
        d = by_category.get(category.strip().lower())
        if d is None:
            return
        d[name] = max(0, d.get(name, 0) + delta)
    else:
        # EngineerCraft's Ingredients list doesn't tag category — raw/
        # manufactured/encoded material names never overlap, so look it
        # up by whichever category dict already has it.
        for d in by_category.values():
            if name in d:
                d[name] = max(0, d.get(name, 0) + delta)
                return


def scan_latest_materials(journal_dir: Path) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    journal_dir = Path(journal_dir)
    raw: Dict[str, int] = {}
    manufactured: Dict[str, int] = {}
    encoded: Dict[str, int] = {}
    by_category = {"raw": raw, "manufactured": manufactured, "encoded": encoded}

    files = sorted(journal_dir.glob("Journal.*.log")) if journal_dir.exists() else []
    if not files:
        return raw, manufactured, encoded

    snapshot_idx: Optional[Tuple[int, int]] = None
    for file_idx in range(len(files) - 1, -1, -1):
        last_event = None
        last_line = -1
        try:
            with files[file_idx].open("r", encoding="utf-8", errors="replace") as f:
                for line_idx, line in enumerate(f):
                    if '"Materials"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") == "Materials":
                        last_event = event
                        last_line = line_idx
        except OSError:
            continue
        if last_event is not None:
            _apply_snapshot(last_event, by_category)
            snapshot_idx = (file_idx, last_line)
            break

    if snapshot_idx is None:
        return raw, manufactured, encoded

    snap_file_idx, snap_line = snapshot_idx
    for file_idx in range(snap_file_idx, len(files)):
        start_line = snap_line + 1 if file_idx == snap_file_idx else 0
        try:
            with files[file_idx].open("r", encoding="utf-8", errors="replace") as f:
                for line_idx, line in enumerate(f):
                    if line_idx < start_line:
                        continue
                    if not any(tok in line for tok in ('"MaterialCollected"', '"MaterialDiscarded"', '"MaterialTrade"', '"EngineerCraft"')):
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name == "MaterialCollected":
                        _adjust(by_category, event.get("Category"), event.get("Name"), int(event.get("Count") or 0))
                    elif name == "MaterialDiscarded":
                        _adjust(by_category, event.get("Category"), event.get("Name"), -int(event.get("Count") or 0))
                    elif name == "MaterialTrade":
                        paid = event.get("Paid")
                        received = event.get("Received")
                        if isinstance(paid, dict):
                            _adjust(by_category, paid.get("Category"), paid.get("Name"), -int(paid.get("Count") or 0))
                        if isinstance(received, dict):
                            _adjust(by_category, received.get("Category"), received.get("Name"), int(received.get("Count") or 0))
                    elif name == "EngineerCraft":
                        for ingredient in (event.get("Ingredients") or []):
                            if isinstance(ingredient, dict):
                                _adjust(by_category, None, ingredient.get("Name"), -int(ingredient.get("Count") or 0))
        except OSError:
            continue

    return raw, manufactured, encoded
