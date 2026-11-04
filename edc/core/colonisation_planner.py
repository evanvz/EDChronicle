# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Rule-based colonisation planner: places facilities into a system's known slots by system type. Pure, no Qt.

Sources (community-reported, not official):
  Mega Guide = port cost ramp (primary free, not counted)
  101 = Colonization 101 (CMDR PhoenixBlue0): solo Coriolis, group Ocellus/Orbis primary
  Evan = owner decisions, spec 2026-11-04-colonisation-system-planner-design
Facility costs, rewards, requirements and effects: settings/colonisation_facilities.json (Raven Colonial + ED wiki).
"""

from edc.core import colonisation_facilities
from edc.core.colonisation_design import _clash

TYPES = ("refinery", "service", "full")
TYPE_NAMES = {"refinery": "Refinery", "service": "Service stop", "full": "Full build"}

_LOCS = ("orbital", "surface")
_T1_ORBITAL = ("satellite_installation", "comms_installation", "relay_installation")  # no economy, +1 T2
_THEMES = ("Refinery", "Industrial", "HighTech", "Extraction", "Agriculture", "Military", "Tourism")  # tie order
_FAMILIES = {  # theme: (medium settlement, large settlement, cluster hub)
    "Refinery": ("mining_settlement_medium", "mining_settlement_large", "refinery_hub"),
    "Industrial": ("industrial_settlement_medium", "industrial_settlement_large", "industrial_hub"),
    "HighTech": ("bio_settlement_medium", "bio_settlement_large", "high_tech_hub"),
    "Extraction": ("mining_settlement_medium", "mining_settlement_large", "extraction_hub"),
    "Agriculture": ("agriculture_settlement_medium", "agriculture_settlement_large", "civilian_hub"),
    "Military": ("military_settlement_medium", "military_settlement_large", "military_hub"),
    "Tourism": ("tourist_settlement_medium", "tourist_settlement_large", "space_bar_installation"),
}
# hubs carry economy null in the data: inferred from the hub's family, unverified
_HUB_ECON = {"refinery_hub": "Refinery", "industrial_hub": "Industrial", "high_tech_hub": "HighTech",
             "extraction_hub": "Extraction", "military_hub": "Military"}
_FIVE = "Up to 5 facilities can be under construction at once"


def _first(*pairs):
    return next(((v, src) for v, src in pairs if v is not None), (None, None))


def slot_table(system: dict, raven: dict | None) -> list[dict]:
    rows = []
    for b in system.get("bodies") or []:
        r_orb, r_sur = (raven or {}).get(b["name"]) or (None, None)
        orb, orb_src = _first((b.get("orbital_slots"), "entered"), (r_orb, "raven"))
        sur, sur_src = _first((b.get("surface_slots"), "entered"), (r_sur, "raven"), (b.get("ground_slots"), "est"))
        rows.append({"body_id": b.get("body_id"), "name": b["name"], "orbital": orb, "surface": sur,
                     "orbital_source": orb_src, "surface_source": sur_src})
    return rows


def port_cost(tier: int, n: int) -> int:
    # Mega Guide: T2 3, 3, 5, 7, 9 ... (3 + (n-2)*2); T3 6, 6, 12, 18, 24 ... ((n-1)*6)
    if tier == 2:
        return 3 if n <= 2 else 3 + (n - 2) * 2
    return 6 if n <= 2 else (n - 1) * 6


def _theme(bodies: list[dict]) -> str:
    counts = {}
    for b in bodies:
        for e in set(b.get("economies") or []) - {"Colony", "Terraforming"}:
            counts[e] = counts.get(e, 0) + 1
    return max(_THEMES, key=lambda e: (counts.get(e, 0), -_THEMES.index(e)))


def plan(system: dict, slots: list[dict], primary_body: str, group: bool, kind: str) -> dict:
    if kind not in TYPES:
        raise ValueError(f"unknown plan kind: {kind!r}")
    fac = colonisation_facilities.load()
    bodies = {b["name"]: b for b in system.get("bodies") or []}
    steps, warnings, note = [], [], None
    free = {}
    for r in slots:
        for loc in _LOCS:
            if r[loc] is None:
                warnings.append(f"{loc} slots unknown: {r['name']}")
            else:
                free[(r["name"], loc)] = r[loc]
    unknown = [r["name"] for r in slots if r["orbital"] is None or r["surface"] is None]

    # twin of colonisation_design.plan_system's primary rule (101): keep both in step
    # 101: solo Coriolis; group T3, Ocellus when the body has rings, else Orbis. Free, adds its reward.
    pkey = ("ocellus_starport" if bodies.get(primary_body, {}).get("rings") else "orbis_starport") if group \
        else "coriolis_starport"
    pf = fac[pkey]
    if free.get((primary_body, "orbital")) == 0:
        warnings.append("primary body shows no orbital slot")
    elif (primary_body, "orbital") in free:
        free[(primary_body, "orbital")] -= 1
    bal = [pf["cp_reward"]["t2"], pf["cp_reward"]["t3"]]
    steps.append({"title": f"Primary: {pf['name'].removesuffix(' Starport')}", "facility": pkey, "body": primary_body,
                  "location": "orbital", "t2": bal[0], "t3": bal[1], "note": "free", "haul": pf["haul"]})
    stats = dict(pf["effects"])
    total = {"haul": pf["haul"], "score": pf["score"]}
    built = {pkey}
    ports = [0]  # non-primary T2/T3 ports placed (Mega Guide: the primary doesn't count)

    def place(key, body, note=None):
        f = fac[key]
        loc = f["location"]
        if free.get((body, loc), 0) < 1 or (f["requires"] and not built & set(f["requires"])):
            return False
        cost = [f["cp_cost"]["t2"], f["cp_cost"]["t3"]]
        if f["port"]:
            c = port_cost(f["tier"], ports[0] + 1)
            cost = [c, 0] if f["tier"] == 2 else [0, c]
            note = f"port {ports[0] + 1}: {c} T{f['tier']} points"
        if bal[0] < cost[0] or bal[1] < cost[1]:
            return False
        ports[0] += f["port"]
        free[(body, loc)] -= 1
        bal[0] += f["cp_reward"]["t2"] - cost[0]
        bal[1] += f["cp_reward"]["t3"] - cost[1]
        for k, v in f["effects"].items():
            stats[k] += v
        total["haul"] += f["haul"]
        total["score"] += f["score"]
        built.add(key)
        steps.append({"title": f["name"], "facility": key, "body": body, "location": loc,
                      "t2": bal[0], "t3": bal[1], "note": note, "haul": f["haul"]})
        return True

    def secure(order):  # Pass 6: security
        room = lambda loc: next((n for n in order if free.get((n, loc), 0) > 0), None)
        while stats["sec"] < 0:
            n = room("orbital")
            if n and "relay_installation" not in built and place("relay_installation", n):
                continue
            if n and place("security_installation", n):
                continue
            n = room("surface")
            if not (n and place("military_settlement_medium", n)):
                break

    if kind == "service":
        if pf["tier"] == 3:
            note = "Tier 3 primary: all services from the start"
            secure([r["name"] for r in slots])
        elif not place("comms_installation", primary_body, "Cartographics/Vista link"):
            warnings.append("no free orbital slot on the primary body for the Cartographics/Vista link")

    elif kind == "refinery":
        if not place("comms_installation", primary_body, "T2 point and link") \
                and not any(place("comms_installation", b, "T2 point") for b in bodies):
            warnings.append("no free orbital slot for the Comms installation")
        if free.get((primary_body, "surface"), 0) < 1:
            warnings.append("no surface slot on the primary body: no Refinery Hub")
        elif not place("refinery_hub", primary_body):
            warnings.append("not enough T2 points for the Refinery Hub")
        elif not place("mining_settlement_large", primary_body):
            place("mining_settlement_medium", primary_body)

    elif kind == "full":
        cluster = {n: b.get("cluster") for n, b in bodies.items()}
        clusters = list(dict.fromkeys([cluster.get(primary_body)] + [cluster[r["name"]] for r in slots]))
        themes = {c: _theme([b for b in bodies.values() if b.get("cluster") == c]) for c in clusters}
        order = sorted((r["name"] for r in slots), key=lambda n: clusters.index(cluster[n]))
        fam = {n: _FAMILIES[themes[cluster[n]]] for n in order}
        room = lambda loc: next((n for n in order if free.get((n, loc), 0) > 0), None)

        for n in order:  # Pass 1: one medium settlement of the theme per body
            place(fam[n][0], n)
        # Pass 2: Tier 1 installations for T2, one orbital slot kept per body for a Tier 3 port.
        # Industrial Hub needs a Mining/Industrial installation first (wiki), so it leads when a cluster is Industrial.
        queue = ["mining_industrial_installation"] if "Industrial" in themes.values() else []
        i = 0
        for n in order:
            while free.get((n, "orbital"), 0) > 1:
                if queue:
                    key = queue.pop(0)
                else:
                    key, i = _T1_ORBITAL[i % 3], i + 1
                if not place(key, n):
                    break
        # Pass 2's kept orbital slot per body stays held for a Tier 3 port until Pass 4
        held = [k for k, v in free.items() if k[1] == "orbital" and v > 0]
        for k in held:
            free[k] -= 1
        # Hold back 1 T2 and one slot per cluster that can take its hub
        hubs = []
        for c in clusters:
            h = fac[_FAMILIES[themes[c]][2]]
            n = next((n for n in order if cluster[n] == c and free.get((n, h["location"]), 0) > 0), None)
            if n and (not h["requires"] or built & set(h["requires"])):
                hubs.append((n, h["location"]))
                free[(n, h["location"])] -= 1
        for n in order:  # Pass 3: large settlements while T2 lasts
            while bal[0] > len(hubs) and place(fam[n][1], n):
                pass
        for k in hubs:
            free[k] += 1
        # Pass 5 before Pass 4: hub T3 rewards help pay for ports
        for c in clusters:  # Pass 5: one cluster hub, when its requirement is met
            next((n for n in order if cluster[n] == c and place(_FAMILIES[themes[c]][2], n)), None)
        for k in held:
            free[k] += 1
        while True:  # Pass 4: Tier 3 ports, orbital first, then surface when no orbital slot is left
            n = room("orbital")
            key = "dodec_starport" if n else "large_planetary_port"
            n = n or room("surface")
            if not (n and place(key, n)):
                break
        secure(order)
        # Pass 7 fallback: a zero-cost surface facility of the theme's economy, else civilian
        cheap = {c: next((k for k, f in fac.items() if f["location"] == "surface" and not f["port"]
                          and (f["economy"] or "").lower() == themes[c].lower() and not any(f["cp_cost"].values())),
                         "civilian_surface_outpost") for c in clusters}
        for n in order:  # Pass 7: fill every slot left
            while free.get((n, "orbital"), 0) and place(_T1_ORBITAL[i % 3], n):
                i += 1
            # a military settlement while sec is below 0, so the final fill can't undo Pass 6
            while ((stats["sec"] < 0 and place("military_settlement_medium", n))
                   or place(fam[n][0], n) or place(cheap[cluster[n]], n)):
                pass

    if stats["sec"] < 0:
        warnings.append("security below 0 after the plan")
    # Spec: keep each market (primary body, any placed port's body) to at most two economies (strong link: same body)
    ignore = {"Colony", "Terraforming"}
    for m in dict.fromkeys([primary_body] + [s["body"] for s in steps[1:] if fac[s["facility"]]["port"]]):
        econ = {e.replace("Hightech", "HighTech") for e in (bodies.get(m, {}).get("economies") or [])
                + [fac[s["facility"]]["economy"] or _HUB_ECON.get(s["facility"]) for s in steps if s["body"] == m]
                if e} - ignore
        if _clash(econ):
            short = m.removeprefix(system.get("name") or "").strip() or m
            warnings.append(f"{short} market: {', '.join(sorted(econ))} — a third economy gets cannibalised")
    warnings.append(_FIVE)
    if pf["tier"] == 1 and stats["tech"] < 35:
        warnings.append(f"tech level {stats['tech']} below 35: Tier 1 port shipyard/outfitting need 35 "
                        "(unverified that this sum is the game's tech level)")
    unused = {loc: sum(v for (_, l), v in free.items() if l == loc) for loc in _LOCS}
    return {"steps": steps, "warnings": warnings, "note": note, "unused": unused, "unknown": unknown,
            "outcome": {"stats": stats, **total}}
