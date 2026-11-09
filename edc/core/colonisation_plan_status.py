def primary_depot(depots, system_address):
    mine = [d for d in depots if d["system_address"] == system_address]
    return min(mine, key=lambda d: d["id"]) if mine else None


def status_updates(stored, depots, system_address, primary):
    by_market = {d["market_id"]: d for d in depots if d["system_address"] == system_address}
    pd = primary_depot(depots, system_address)
    key = (primary["body"], primary["location"], primary["slot_index"])
    out = []
    primary_row = None
    for r in stored:
        if (r["body"], r["location"], r["slot_index"]) == key:
            primary_row = r
        if r["market_id"] is None:
            continue
        d = by_market.get(r["market_id"])
        if d and d["complete"] and r["status"] != "Complete":
            out.append({**r, "status": "Complete"})
    if pd:
        status = "Complete" if pd["complete"] else "Building"
        if primary_row is None:
            out.append({**primary, "status": status, "market_id": pd["market_id"]})
        elif primary_row["market_id"] is None:
            out.append({**primary_row, "status": status, "market_id": pd["market_id"]})
    return out


def unlinked_depots(stored, depots, system_address):
    linked = {r["market_id"] for r in stored if r["market_id"] is not None}
    pd = primary_depot(depots, system_address)
    return [d for d in depots if d["system_address"] == system_address
            and d["market_id"] not in linked and d is not pd]
