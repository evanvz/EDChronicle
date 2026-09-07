# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

from __future__ import annotations
from typing import Any, Dict, List

def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Everything not yet split: CGs, ship targeting, vouchers.
    Returns True if handled.
    """

    if name == "RedeemVoucher":
        # Session ledger (bounties/vouchers)
        amt = event.get("Amount")
        if isinstance(amt, int):
            engine.state.session_voucher_earnings += amt
            msgs.append(f"Voucher redeemed: {amt:,} cr")
        return True

    elif name == "CommunityGoalJoin":
        cgid = event.get("CGID")
        if isinstance(cgid, int):
            # Store minimal info; the full snapshot arrives via "CommunityGoal"
            rec = engine.state.community_goals.get(cgid, {})
            rec.update(
                {
                    "CGID": cgid,
                    "Title": event.get("Name") or rec.get("Title"),
                    "SystemName": event.get("System") or rec.get("SystemName"),
                }
            )
            engine.state.community_goals[cgid] = rec
            if rec.get("Title"):
                msgs.append(f"CG joined: {rec.get('Title')}")
        return True

    elif name == "CommunityGoal":
        cgid = event.get("CGID")
        if isinstance(cgid, int):
            rec = engine.state.community_goals.get(cgid, {})
            rec.update(event)
            engine.state.community_goals[cgid] = rec
        return True

    elif name == "ShipTargeted":
        # Basic target tracking
        tgt = event.get("Ship")
        if isinstance(tgt, str) and tgt.strip():
            engine.state.last_target_ship = tgt
        pilot = event.get("PilotName_Localised") or event.get("PilotName")
        if isinstance(pilot, str) and pilot.strip():
            engine.state.last_target_pilot = pilot
        return True

    return False