"""Full-history scan to reconstruct fleet carrier status (own + squadron's
shared carrier) at app startup — same reasoning as bounty_scanner.py: the
live bootstrap only re-reads the tail of the current journal, so a carrier
whose last CarrierStats/CarrierJump happened in an earlier session would
otherwise show as "no data" until the player re-triggers one live.

Reuses edc.engine.handlers.fleet_carrier.handle() directly against a bare
GameState so the scan can never drift from the live event-handling logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from edc.core.state import GameState
from edc.engine.handlers.fleet_carrier import handle as _carrier_handle

_CARRIER_EVENT_NAMES = {
    "CarrierJump", "CarrierBuy", "CarrierStats", "CarrierJumpRequest",
    "CarrierJumpCancelled", "CarrierBankTransfer", "CarrierDepositFuel",
    "CarrierFinance", "CarrierTradeOrder", "CarrierLocation",
}


class _FakeEngine:
    def __init__(self, state: GameState):
        self.state = state


def scan_carrier_status(journal_dir: Path) -> GameState:
    journal_dir = Path(journal_dir)
    state = GameState()
    engine = _FakeEngine(state)
    if not journal_dir.exists():
        return state

    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Carrier' not in line:
                        continue
                    try:
                        event: Dict[str, Any] = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name not in _CARRIER_EVENT_NAMES:
                        continue
                    _carrier_handle(engine, name, event, [])
        except OSError:
            continue

    return state
