"""One-shot full-history scan to reconstruct the currently unredeemed
combat bond/bounty voucher total at app startup. Mirrors bounty_scanner.py's
reasoning: this must survive app restarts and journal-file boundaries — an
unredeemed bond in-game doesn't clear just because the app restarted — so
this replays every journal file chronologically rather than relying solely
on the persisted session ledger (which only helps if every prior session
saved cleanly before exiting).

Bounty vouchers (Bounty event) and combat bonds (FactionKillBond event) both
accumulate into the same in-game "combat rewards" pool and are cleared
together by a RedeemVoucher of Type "bounty" or "CombatBond" — matching
event_engine.py's own combat_unsold_total handling exactly.

Also separately reconstructs per-AwardingFaction unredeemed combat bond
totals (active_combat_bonds) -- a combat bond can only be redeemed at a
station the awarding faction controls (via Contacts, not Interstellar
Factors), unlike a bounty voucher which can go to any station, so knowing
which faction each bond belongs to is what a "redeem this" pointer needs.
Confirmed live: RedeemVoucher(Type="CombatBond") names exactly one faction
per event ("Faction" field), unlike the bounty type's "Factions" array.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple


def scan_unredeemed_combat_total(journal_dir: Path) -> Tuple[int, Dict[str, int]]:
    """Returns (total, active_combat_bonds) -- see module docstring."""
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return 0, {}

    total = 0
    bonds: Dict[str, int] = {}
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Bounty"' not in line and '"FactionKillBond"' not in line and '"RedeemVoucher"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name == "Bounty":
                        reward = event.get("TotalReward")
                        if isinstance(reward, int):
                            total += reward
                    elif name == "FactionKillBond":
                        reward = event.get("Reward")
                        if isinstance(reward, int):
                            total += reward
                            faction = event.get("AwardingFaction")
                            if isinstance(faction, str) and faction:
                                bonds[faction] = bonds.get(faction, 0) + reward
                    elif name == "RedeemVoucher" and event.get("Type") in ("bounty", "CombatBond"):
                        total = 0
                        if event.get("Type") == "CombatBond":
                            redeemed_faction = event.get("Faction")
                            if isinstance(redeemed_faction, str) and redeemed_faction:
                                bonds.pop(redeemed_faction, None)
        except OSError:
            continue

    return total, bonds
