# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "settings" / "colonisation_facilities.json"


@lru_cache(maxsize=1)
def load() -> dict[str, dict]:
    return json.loads(_PATH.read_text(encoding="utf-8"))["facilities"]


def by_rc_type(build_type: str) -> dict | None:
    return next((f for f in load().values() if build_type in f["rc_types"]), None)
