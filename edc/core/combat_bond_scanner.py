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
"""
from __future__ import annotations

import json
from pathlib import Path


def scan_unredeemed_combat_total(journal_dir: Path) -> int:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return 0

    total = 0
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
                    elif name == "RedeemVoucher" and event.get("Type") in ("bounty", "CombatBond"):
                        total = 0
        except OSError:
            continue

    return total
