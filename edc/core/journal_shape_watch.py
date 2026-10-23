# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Flags journal events and fields the app has never seen -- a game update
(Law & Disorder reworks crime in December 2026) can add or change events the
app relies on. The baseline is every event name and top-level field in all
local journals (about 6 s for 380 MB), built once in the background and kept
in data/journal_shapes.json; after that each live event is checked against it.

ponytail: top-level fields only; a change inside a nested array (Factions[],
Materials[]) isn't seen. Look one level deeper if that ever matters.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Set

log = logging.getLogger(__name__)


class JournalShapeWatch:
    def __init__(self, path: Path):
        self._path = path
        self._shapes: Optional[Dict[str, Set[str]]] = None   # None until the baseline exists
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._shapes = {name: set(keys) for name, keys in data.items()}
        except (OSError, ValueError, AttributeError):
            pass

    def start_baseline(self, journal_dir: Optional[str]) -> None:
        """First run only: scan every journal in a background thread."""
        if self._shapes is not None or not journal_dir:
            return
        threading.Thread(target=self._build, args=(Path(journal_dir),), daemon=True,
                         name="journal-shape-baseline").start()

    def _build(self, journal_dir: Path) -> None:
        shapes: Dict[str, Set[str]] = {}
        for f in sorted(journal_dir.glob("Journal.*.log")):
            try:
                with open(f, encoding="utf-8", errors="replace") as h:
                    for line in h:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict) and isinstance(event.get("event"), str):
                            shapes.setdefault(event["event"], set()).update(event)
            except OSError:
                continue
        self._shapes = shapes
        self._save()
        log.info("Journal baseline: %d event types from %s", len(shapes), journal_dir)

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps({n: sorted(k) for n, k in sorted(self._shapes.items())}),
                                  encoding="utf-8")
        except OSError:
            log.exception("Failed to save %s", self._path)

    def observe(self, event: dict) -> Optional[str]:
        """A one-line note when `event` is a new event type or carries new
        top-level fields (then remembered, so each is reported once), else None."""
        shapes, name = self._shapes, event.get("event")
        # "Status" is Status.json (edc.core.status_watcher), not the journal: its
        # fields come and go with what you're doing (on a planet, in the SRV)
        if shapes is None or not isinstance(name, str) or name.startswith("_") or name == "Status":
            return None
        known = shapes.get(name)
        if known is None:
            shapes[name] = set(event)
            self._save()
            return f"New journal event: {name}"
        new = set(event) - known
        if not new:
            return None
        known.update(new)
        self._save()
        return f"Journal event {name} has new fields: {', '.join(sorted(new))}"
