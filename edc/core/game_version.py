# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Notices a new Elite Dangerous game version in the journal (Fileheader /
LoadGame "gameversion"), so a game update that may change journal events or
game rules the app relies on gets a look -- see Frontier's update notes."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def note_game_version(path: Path, version: object) -> Optional[str]:
    """Stores `version`; returns the previously stored one when it differs,
    else None (same version, first run, or no version)."""
    if not isinstance(version, str) or not version.strip():
        return None
    version = version.strip()
    try:
        previous = json.loads(path.read_text(encoding="utf-8")).get("gameversion")
    except (OSError, ValueError, AttributeError):
        previous = None
    if previous == version:
        return None
    try:
        path.write_text(json.dumps({"gameversion": version}), encoding="utf-8")
    except OSError:
        log.exception("Failed to save %s", path)
    return previous
