"""Phased colonisation build plan for one system, from the hub's /api/colonisation-system body details. Pure, no Qt.

Clusters and ground slots come from the hub; this module only templates the plan and the poor-pick verdict.
Sources (community-reported, not official):
  Dubior = CMDR Dubior's Advanced ED Colonization Guide (ref. 2026-08-11)
  101 = Colonization 101 (CMDR PhoenixBlue0)
  DaftMav = Service Unlocks flowchart
  Evan = owner decisions, 2026-10-30
Official: Frontier Trailblazers Update 3.3 notes (station service activation), read 2026-10-31.
Construction points: ED wiki "System Colonisation" facility tables (rev. 2026-10-26) and gaborauth/ed-colonisation-planner
  (primary is free, read 2026-10-31).
"""

# Poor-pick thresholds (builder's call, spec "System design window")
POOR = {
    "max_ls": 4000,  # primary body farther than this from arrival: too far for a service stop (Evan: shorter is better)
    "min_slots": 1,  # a cluster moon needs at least this many known ground slots to take hubs and settlements (Dubior)
}

# Tonnage (Dubior / 101): Coriolis ~70 kt, T3 Orbis/Ocellus ~250 kt; a primary port must finish within 4 weeks (101)
_CORIOLIS = "about 70 kt hauled within 4 weeks"
_T3 = "about 250 kt hauled within 4 weeks: needs a group"
_BASICS = ["Repair, refuel, rearm", "Market", "Shipyard", "Outfitting"]  # default on T2/T3 orbitals (DaftMav)
_NAMES = {"HighTech": "High Tech"}


def _clash(econ: set) -> bool:
    # Twin of EDDataHub eddatahub/service_stop.py `cannibalises`: change both together
    # Dubior "Mixed Economy Setups": Industrial and High Tech clash with any other economy (covers Refinery + Industrial)
    return len(econ) > 1 and bool(econ & {"Industrial", "HighTech"})


def _econ_text(econ) -> str:
    return " + ".join(_NAMES.get(e, e) for e in sorted(econ))


def _short(name: str, system: str) -> str:
    return name.removeprefix(system).strip() or name


def plan_system(system: dict, primary_body: str, group: bool) -> dict:
    out = {"poor": None, "steps": [], "warnings": [], "note": None}
    bodies = system.get("bodies") or []
    # keys missing (old hub) or all None (migration 020 deployed, system not re-imported yet)
    if (not bodies or any("cluster" not in b or "ground_slots" not in b for b in bodies)
            or system.get("service_score") is None or all(b["cluster"] is None for b in bodies)):
        return {**out, "poor": "Hub has no body details yet"}
    p = next((b for b in bodies if b["name"] == primary_body), None)
    if p is None:
        return {**out, "poor": f"Primary body not in this system: {primary_body}"}
    if p["cluster"] is None:
        return {**out, "poor": "Primary slot on a star or belt: no planet cluster for hubs and settlements"}
    if p.get("distance_ls") is not None and p["distance_ls"] > POOR["max_ls"]:
        return {**out, "poor": f"Primary body too far out: {p['distance_ls']:,.0f} ls (limit {POOR['max_ls']:,} ls)"}
    cluster = [b for b in bodies if b["cluster"] == p["cluster"] and b is not p]
    moons = [b for b in cluster if b.get("landable") and (b["ground_slots"] or 0) >= POOR["min_slots"]]
    if not moons:
        if any(b.get("landable") and b["ground_slots"] is None for b in cluster):
            return {**out, "poor": "Ground slots unknown for this cluster: scan the bodies"}
        return {**out, "poor": "No landable moon with known ground slots in this cluster"}

    steps, warnings, notes = out["steps"], out["warnings"], []
    if p.get("distance_ls") is None:
        warnings.append("Primary body distance unknown: far-out check skipped")
    main = set(p.get("economies") or []) - {"Terraforming"}
    if _clash(main):
        warnings.append(f"Main port natural economies {_econ_text(main)} clash (Dubior): expect a thinner market")

    bal = [0, 0]  # construction points T2, T3 after each step (wiki facility tables, rev. 2026-10-26)

    def step(title, body, unlocks, needs, adds=None, t2=0, t3=0, gain=None):
        bal[0] += t2
        bal[1] += t3
        gain = gain or ", ".join(f"{v:+d} {k}" for k, v in (("T2", t2), ("T3", t3)) if v) or "none"
        steps.append({"title": title, "body": body, "unlocks": unlocks, "needs": needs,
                      "points": f"{gain}; then T2 {bal[0]}, T3 {bal[1]}"})
        if bal[0] < 0:
            warnings.append(f"{title} needs {-bal[0]} more T2 point(s): build a Tier 1 facility first (e.g. Satellite, Space Farm)")
            bal[0] = 0
        if adds and adds not in main and _clash(main | {adds}):
            warnings.append(f"{title} adds {_NAMES.get(adds, adds)} next to the main port's {_econ_text(main)} (Dubior)")

    # 1. Primary port (101): solo Coriolis; group T3, Ocellus when the body has rings, else Orbis
    # The primary is free; a Coriolis primary still grants +1 T3 (gaborauth planner, in-game checked 2026-07-30)
    if group:
        step(f"Primary: {'Ocellus' if p.get('rings') else 'Orbis'}", p["name"],
             _BASICS + ["Universal Cartographics", "Vista Genomics"], _T3, gain="free (primary)")
    else:
        step("Primary: Coriolis", p["name"], _BASICS, _CORIOLIS, t3=1, gain="free (primary), +1 T3")
        # 2. Same orbit, strong link (Update 3.3: Satellite, Comms or Relay); not Relay: it adds High Tech (Evan)
        step("Comms installation", p["name"], ["Universal Cartographics", "Vista Genomics", "Security"],
             "Same orbit as the primary; not a Relay, it adds High Tech to the main port", t2=1)
    # 3. Tier 1 surface outpost on the primary body (Dubior): a Tier 3 Planetary Port costs 6 T3, out of reach here
    if p.get("landable") and p["ground_slots"] != 0:
        step("Civilian Planetary Outpost on the primary body", p["name"], ["Population", "Market supply"],
             "Primary port built" + ("; ground slots unknown, check in Architect View" if p["ground_slots"] is None else ""),
             t2=1)
    # 4. Mining Installation, then Industrial Hub on a moon (wiki: the hub requires a Mining Installation)
    # Update 3.3: an Industrial Hub's shipyard/outfitting reach only Tier 1 surface ports it strong-links to (same body)
    mine = min(moons, key=lambda b: "Extraction" not in (b.get("economies") or []))
    step("Mining Installation + Industrial Hub", mine["name"],
         ["Development level", "Shipyard and outfitting at a Tier 1 surface port on the same body"],
         "Mining Installation first", "Industrial", t3=1, gain="+1 T2 then -1 T2, +1 T3")
    # 5. High Tech Hub on a different cluster so the main port keeps its top two (Evan, market before outfitting)
    ht_clusters = {b["cluster"] for b in bodies if b["cluster"] not in (None, p["cluster"])
                   and "HighTech" in (b.get("economies") or [])}
    ht = next((b for b in bodies if b["cluster"] in ht_clusters and b.get("landable") and (b["ground_slots"] or 0) > 0), None)
    if ht:
        # Update 3.3: a High Tech Hub anywhere in the system gives outfitting to Tier 1 ports (not Military/Industrial)
        step("High Tech Hub", ht["name"], ["Outfitting at Tier 1 ports", "Tech level"], "Another cluster than the main port",
             t2=-1, t3=1)
    else:
        notes.append("No other cluster gives High Tech: outfitting stock stays at the default")
    # 6. Optional growth (Dubior): Space Farm / Agriculture settlement on a bio or terraformable body
    farm = next((b for b in cluster if b.get("bio") or b.get("terraformable")), None)
    if farm:
        step("Optional: Space Farm or Agriculture settlement", farm["name"], ["Population", "Agriculture market"],
             None, "Agriculture", t2=1)

    # The hub's score reason names its best cluster; say so when the user picked another one
    sysname = system.get("name") or ""
    reason = system.get("service_reason") or ""
    root = next((b for b in bodies if b.get("body_id") == p["cluster"]), p)
    best = reason.split(":")[0].split(" at ")[0]
    if ":" in reason and not best.endswith(" " + _short(root.get("name") or f"Body {root.get('body_id')}", sysname)):
        notes.append(f"Hub's best cluster is {best}")
    out["note"] = "; ".join(notes) or None
    return out
