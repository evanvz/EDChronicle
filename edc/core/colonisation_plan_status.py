def own_systems(depots):
    """{system_address: system_name} of every system with a construction site, in depot order."""
    return {d["system_address"]: d["system_name"] for d in depots
            if isinstance(d.get("system_address"), int) and d.get("system_name")}


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


def body_links(steps, stored, depots, system_address):
    """Surface sites whose body is known and that no step is linked to: each takes the first unfinished,
    unlinked planned step on that body. A removed site only counts once it is complete.
    Call with the primary already linked (status_updates saved): the primary's site is then in `stored`."""
    linked = {r["market_id"] for r in stored if r["market_id"] is not None}
    taken = {(r["body"], r["location"], r["slot_index"]) for r in stored if r["market_id"] is not None}
    out = []
    for d in sorted(depots, key=lambda d: d["id"]):
        body = (d.get("body_name") or "").casefold()
        if (d["system_address"] != system_address or not body or d["market_id"] in linked
                or (d.get("removed") and not d["complete"])):
            continue
        s = next((s for s in steps if s["n"] != 1 and s["location"] == "surface" and s["status"] != "Complete"
                  and (s["body"] or "").casefold() == body
                  and (s["body"], s["location"], s["slot_index"]) not in taken), None)
        if s:
            taken.add((s["body"], s["location"], s["slot_index"]))
            out.append({"facility": s["facility"], "body": s["body"], "location": s["location"],
                        "slot_index": s["slot_index"], "status": "Complete" if d["complete"] else "Building",
                        "market_id": d["market_id"]})
    return out


def unlinked_depots(stored, depots, system_address):
    # The primary's site is linked by status_updates, so it is in `stored` like any other linked site.
    linked = {r["market_id"] for r in stored if r["market_id"] is not None}
    return [d for d in depots if d["system_address"] == system_address
            and d["market_id"] not in linked and not d.get("removed")]
