from __future__ import annotations
from typing import Any, Dict, List

# Fields per the official Journal Manual (Fleet Carriers, §11). Only
# handles events relevant to a carrier the commander owns/is docked at —
# CarrierDecommission/CancelDecommission/CrewServices/ShipPack/ModulePack/
# DockingPermission/NameChanged are not tracked (out of scope for a status
# overview panel).
#
# Squadron members can now see CarrierStats for their SQUADRON's shared
# carrier too (CarrierType:"SquadronCarrier" — confirmed empirically, not
# documented in the older manual), which must not be mistaken for the
# player's own carrier. carrier_owned_market_id is the gate: once we've
# confirmed a specific carrier ID is genuinely the player's own (via
# CarrierBuy, or a non-squadron CarrierStats), every other carrier event
# is only applied if its ID matches.


def _owned_id_matches(engine, event_carrier_id) -> bool:
    owned = engine.state.carrier_owned_market_id
    if owned is None:
        return True  # not yet confirmed either way — accept, as before
    return event_carrier_id == owned


def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Fleet Carrier ownership/status tracking.
    Returns True if handled.
    """

    if name == "CarrierJump":
        # Fired when the player is docked at their carrier as it jumps.
        market_id = event.get("MarketID")
        if not _owned_id_matches(engine, market_id):
            return True
        engine.state.carrier_market_id = market_id or engine.state.carrier_market_id
        system = event.get("StarSystem")
        if isinstance(system, str) and system:
            engine.state.carrier_current_system = system
        engine.state.carrier_next_jump_system = None
        engine.state.carrier_next_jump_body = None
        return True

    elif name == "CarrierBuy":
        engine.state.carrier_owned_market_id = event.get("CarrierID")
        engine.state.carrier_market_id = event.get("CarrierID")
        engine.state.carrier_callsign = event.get("Callsign") or engine.state.carrier_callsign
        location = event.get("Location")
        if isinstance(location, str) and location:
            engine.state.carrier_current_system = location
        msgs.append("Fleet Carrier purchased.")
        return True

    elif name == "CarrierStats":
        if event.get("CarrierType") == "SquadronCarrier":
            return True
        engine.state.carrier_owned_market_id = event.get("CarrierID") or engine.state.carrier_owned_market_id
        engine.state.carrier_market_id = event.get("CarrierID") or engine.state.carrier_market_id
        engine.state.carrier_callsign = event.get("Callsign") or engine.state.carrier_callsign
        engine.state.carrier_name = event.get("Name") or engine.state.carrier_name
        engine.state.carrier_docking_access = event.get("DockingAccess")
        allow_notorious = event.get("AllowNotorious")
        engine.state.carrier_allow_notorious = allow_notorious if isinstance(allow_notorious, bool) else None
        fuel = event.get("FuelLevel")
        engine.state.carrier_fuel_level = fuel if isinstance(fuel, int) else None
        rng_curr = event.get("JumpRangeCurr")
        rng_max = event.get("JumpRangeMax")
        engine.state.carrier_jump_range_curr = float(rng_curr) if isinstance(rng_curr, (int, float)) else None
        engine.state.carrier_jump_range_max = float(rng_max) if isinstance(rng_max, (int, float)) else None
        pending = event.get("PendingDecommission")
        engine.state.carrier_pending_decommission = pending if isinstance(pending, bool) else None

        space = event.get("SpaceUsage")
        engine.state.carrier_space_usage = dict(space) if isinstance(space, dict) else {}

        finance = event.get("Finance")
        engine.state.carrier_finance = dict(finance) if isinstance(finance, dict) else {}
        return True

    elif name == "CarrierJumpRequest":
        carrier_id = event.get("CarrierID")
        if not _owned_id_matches(engine, carrier_id):
            return True
        engine.state.carrier_market_id = carrier_id or engine.state.carrier_market_id
        system = event.get("SystemName")
        engine.state.carrier_next_jump_system = system if isinstance(system, str) and system else None
        body = event.get("Body")
        engine.state.carrier_next_jump_body = body if isinstance(body, str) and body else None
        return True

    elif name == "CarrierJumpCancelled":
        engine.state.carrier_next_jump_system = None
        engine.state.carrier_next_jump_body = None
        return True

    elif name == "CarrierBankTransfer":
        carrier_balance = event.get("CarrierBalance")
        if isinstance(carrier_balance, int):
            engine.state.carrier_finance["CarrierBalance"] = carrier_balance
        return True

    elif name == "CarrierDepositFuel":
        total = event.get("Total")
        if isinstance(total, int):
            engine.state.carrier_fuel_level = total
        return True

    elif name == "CarrierFinance":
        for key in ("TaxRate", "CarrierBalance", "ReserveBalance", "AvailableBalance", "ReservePercent"):
            val = event.get(key)
            if isinstance(val, int):
                engine.state.carrier_finance[key] = val
        return True

    elif name == "CarrierTradeOrder":
        commodity = event.get("Commodity")
        if not isinstance(commodity, str) or not commodity:
            return True
        key = commodity.strip().lower()
        if event.get("CancelTrade"):
            engine.state.carrier_trade_orders.pop(key, None)
            return True
        engine.state.carrier_trade_orders[key] = {
            "commodity": commodity,
            "commodity_localised": event.get("Commodity_Localised") or commodity,
            "black_market": bool(event.get("BlackMarket", False)),
            "purchase_order": event.get("PurchaseOrder"),
            "sale_order": event.get("SaleOrder"),
            "price": event.get("Price"),
        }
        return True

    return False
