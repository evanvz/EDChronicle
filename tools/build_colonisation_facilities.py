"""
One-off generator for settings/colonisation_facilities.json.

Sources (fetched live): Raven Colonial site bundle (facility table: tier, CP,
effects, haul, score) and the ED wiki System_Colonisation wikitext (Requires
column; stats cross-checked, disagreements stored under "wiki_differs").

Usage: python tools/build_colonisation_facilities.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

RC = "https://ravencolonial.com/"
WIKI = ("https://elite-dangerous.fandom.com/api.php?action=parse&page=System_Colonisation"
        "&prop=wikitext&format=json")
UA = {"User-Agent": "EDChronicle facility builder"}
OUT = Path(__file__).parent.parent / "settings" / "colonisation_facilities.json"

ALIAS = {"Communication Installation": "comms_installation"}
STAT = {"pop": "Initial Population Increase", "mpop": "Max Population Increase", "sec": "Security",
        "tech": "Tech Level", "wealth": "Wealth", "sol": "Standard of Living", "dev": "Development Level"}

# wiki facility name (lower) -> Raven Colonial displayName2; settlements/outposts added below
WIKI_TO_RC = {
    "coriolis": "Coriolis Starport", "asteroid base": "Asteroid Starport", "ocellus": "Ocellus Starport",
    "orbis": "Orbis Starport", "dodec": "Dodec Starport",
    "criminal outpost": "Pirate Outpost",
    "satellite": "Satellite Installation", "communication station": "Communication Installation",
    "space farm": "Space Farm", "pirate base": "Pirate Base Installation",
    "mining outpost": "Mining/Industrial Installation", "relay station": "Relay Installation",
    "military": "Military Installation", "security station": "Security Installation",
    "government": "Government Installation", "medical": "Medical Installation",
    "research station": "Research Installation", "tourist": "Tourist Installation",
    "bar": "Space Bar Installation",
    "civilian planetary outpost": "Civilian Surface Outpost",
    "industrial planetary outpost": "Industrial Surface Outpost",
    "scientific planetary outpost": "Scientific Surface Outpost",
    "planetary port": "Large Planetary Port",
}
for o in ("Commercial", "Industrial", "Civilian", "Scientific", "Military"):
    WIKI_TO_RC[f"{o.lower()} outpost"] = f"{o} Outpost"
for h in ("Extraction", "Civilian", "Exploration", "Outpost", "Scientific", "Military", "Refinery", "High Tech", "Industrial"):
    WIKI_TO_RC[f"{h.lower()} hub"] = f"{h} Hub"
# wiki settlement type -> RC settlement type (wiki "scientific" is RC "Bio")
SETTLE = {"agricultural": "Agriculture", "extraction": "Mining", "industrial": "Industrial",
          "military": "Military", "scientific": "Bio", "tourism": "Tourist", "mining": "Mining", "agriculture": "Agriculture"}
for w, r in SETTLE.items():
    for size in ("Small", "Medium", "Large"):
        WIKI_TO_RC[f"{size.lower()} {w} settlement"] = f"{r} Settlement: {size}"


def key(name):
    return ALIAS.get(name) or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def game_name(name, surface):
    """Raven Colonial's facility name, reworded to the click path of the game's surface build menu:
    Planetary Port > Outpost | Port, Settlement > category > size, Hub > kind (Evan, in-game 2026-11-14).
    The game says Extraction / Research Bio / Tourism where Raven says Mining / Bio / Tourist."""
    if not surface:
        return name
    m = re.fullmatch(r"(\w+) Surface Outpost", name)
    if m:
        return f"Planetary Port > Outpost > {m[1]}"
    if name == "Large Planetary Port":
        return "Planetary Port > Port"
    m = re.fullmatch(r"(\w+) Settlement: (\w+)", name)
    if m:
        kind = {"Mining": "Extraction", "Bio": "Research Bio", "Tourist": "Tourism"}.get(m[1], m[1])
        return f"Settlement > {kind} > {m[2]}"
    m = re.fullmatch(r"(.+) Hub", name)
    return f"Hub > {m[1]}" if m else name


def fetch_rc():
    html = requests.get(RC, headers=UA, timeout=30).text
    js = re.search(r"/static/js/main\.\w+\.js", html).group(0)
    s = requests.get(RC.rstrip("/") + js, headers=UA, timeout=60).text
    out, i = [], 0
    while (i := s.find('{displayName:"', i)) >= 0:
        depth, j = 0, i
        while True:
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            j += 1
            if depth == 0:
                break
        obj, i = s[i:j], j
        if "buildClass:" not in obj:
            continue
        obj = re.sub(r",unlocks:\[.*?\]", "", obj)
        obj = re.sub(r"([{,])([A-Za-z_]\w*):", r'\1"\2":', obj).replace("!0", "true").replace("!1", "false")
        out.append(json.loads(obj))
    return [o for o in out if o["tier"] > 0 and not o["displayName2"].endswith("?")]


def clean(c):
    c = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", c, flags=re.S)
    c = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", c)
    return c.strip()


def fetch_wiki():
    wt = requests.get(WIKI, headers=UA, timeout=30).json()["parse"]["wikitext"]["*"]
    rows = {}
    for cap in ("Orbital facilities", "Planetary facilities"):
        t = wt[wt.index(f"|+'''{cap}'''"):]
        t = t[:t.index("\n|}")]
        head, *body = t.split("\n|-")
        cols = [clean(h[1:]) for h in head.split("\n") if h.startswith("!")]
        for r in body:
            cells = [clean(l[1:]) for l in r.split("\n") if l.startswith("|")]
            if len(cells) == len(cols):
                rows[cells[0].lower()] = dict(zip(cols, cells))
    return rows


def num(v):
    return int(v) if v.strip() else 0


def cp(text):
    d = {"t2": 0, "t3": 0}
    m = re.fullmatch(r"Tier (\d): (\d+)", text)
    if m:
        d["t" + m[1]] = int(m[2])
    return d


def main():
    rc, wiki = fetch_rc(), fetch_wiki()
    by_name = {r["displayName2"]: r for r in rc}
    w_of = {}
    for wn, row in wiki.items():
        if WIKI_TO_RC.get(wn) in by_name:
            w_of[WIKI_TO_RC[wn]] = row
        else:
            print("wiki row unmatched:", wn)
    resolve = {wn: key(rn) for wn, rn in WIKI_TO_RC.items() if rn in by_name}

    def requires(text):
        if text == "First station":
            return []
        m = re.fullmatch(r"Small/Medium/Large (\w+) Settlement", text)
        if m and m[1].lower() in SETTLE:
            return [resolve[f"{s} {m[1].lower()} settlement"] for s in ("small", "medium", "large")]
        if text.lower() in resolve:
            return [resolve[text.lower()]]
        print("requires unmapped:", text)
        return None

    out = {}
    for r in rc:
        n = r["displayName2"]
        rec = {"name": game_name(n, not r["orbital"]), "rc_types": r["subTypes"] + r.get("altTypes", []), "tier": r["tier"],
               "location": "orbital" if r["orbital"] else "surface", "economy": None, "requires": [],
               "cp_cost": {"t2": 0, "t3": 0}, "cp_reward": {"t2": 0, "t3": 0}}
        rec["cp_cost"]["t%d" % r["needs"]["tier"]] = r["needs"]["count"] if r["needs"]["tier"] else 0
        rec["cp_cost"].pop("t0", None)
        if r["gives"]["tier"]:
            rec["cp_reward"]["t%d" % r["gives"]["tier"]] = r["gives"]["count"]
        rec.update(port=r["buildClass"] == "starport", haul=int(r["haul"]), score=r.get("score", 0), effects=r["effects"])
        diff = {}
        w = w_of.get(n)
        if w:
            rec["economy"] = w["Economy"] or None
            req = requires(w["Requires"])
            if req is None:
                rec["requires_unmapped"] = w["Requires"]
            else:
                rec["requires"] = req
            pairs = [("tier", r["tier"], int(w["Tier"])),
                     ("cp_cost", rec["cp_cost"], cp(w["Construction Points Cost"])),
                     ("cp_reward", rec["cp_reward"], cp(w["Construction Points Reward"]))]
            pairs += [("effects." + k, r["effects"][k], num(w[c])) for k, c in STAT.items() if w[c].strip()]
            diff = {f: [a, b] for f, a, b in pairs if a != b}
        else:
            print("no wiki row:", n)
        rec["wiki_differs"] = diff
        k = key(n)
        assert k not in out, k
        out[k] = rec
    types = [t for v in out.values() for t in v["rc_types"]]
    assert len(types) == len(set(types)), "duplicate rc_type"
    OUT.write_text(json.dumps({"source": "Raven Colonial site bundle + ED wiki System_Colonisation", "read": str(date.today()),
                               "facilities": out}, indent=1) + "\n", encoding="utf-8")
    print(len(out), "facilities;", sum(bool(v["wiki_differs"]) for v in out.values()), "with wiki_differs")
    for k, v in out.items():
        if v["wiki_differs"]:
            print(" ", k, v["wiki_differs"])


if __name__ == "__main__":
    sys.exit(main())
