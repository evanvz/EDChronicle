"""One-shot scan for the most recent Rank/Progress values at app startup.
Both fire once at the start of every journal file (commander login) and
again on promotion — but the app's live bootstrap only re-reads the tail
of the current journal (see journal_watcher.py::_bootstrap_newest_system),
which can miss them in a long-running session. Same pattern as
notoriety_scanner.py: scan journal files newest -> oldest, stop at the
first file with a match.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_IGNORED_KEYS = ("timestamp", "event")


def _categories(event: Dict[str, Any]) -> Dict[str, int]:
    return {k: v for k, v in event.items() if k not in _IGNORED_KEYS and isinstance(v, int)}


def scan_latest_rank_progress(journal_dir: Path) -> Tuple[Optional[Dict[str, int]], Optional[Dict[str, int]]]:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return None, None

    for path in sorted(journal_dir.glob("Journal.*.log"), reverse=True):
        rank = None
        progress = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Rank"' in line:
                        try:
                            event = json.loads(line)
                        except Exception:
                            continue
                        if event.get("event") == "Rank":
                            rank = _categories(event)
                    elif '"Progress"' in line:
                        try:
                            event = json.loads(line)
                        except Exception:
                            continue
                        if event.get("event") == "Progress":
                            progress = _categories(event)
        except OSError:
            continue
        if rank is not None or progress is not None:
            return rank, progress

    return None, None
