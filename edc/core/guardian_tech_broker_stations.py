# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Offline reference table of Guardian Technology Broker stations --
Frontier's own journal StationServices only ever exposes a single generic
"techBroker" tag (no Guardian/Human sub-type), so there's no way to filter
for the Guardian variant specifically from journal/EDDN data alone. Same
shape as rare_commodities.py: a curated (system_name, station_name) list,
cross-referenced against real station_info sightings by
Repository.get_known_guardian_tech_broker_stations() rather than trusted
blindly -- see settings/guardian_tech_broker_stations.json for sourcing.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("edc.guardian_tech_broker_stations")


class GuardianTechBrokerTable:
    def __init__(self, settings_dir: Path, filename: str = "guardian_tech_broker_stations.json"):
        self.path = Path(settings_dir) / filename
        self._stations: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            stations = data.get("stations") if isinstance(data, dict) else None
            self._stations = stations if isinstance(stations, list) else []
        except Exception:
            log.exception("Failed to load guardian_tech_broker_stations.json")
            self._stations = []

    def all(self) -> List[Dict[str, Any]]:
        return list(self._stations)
