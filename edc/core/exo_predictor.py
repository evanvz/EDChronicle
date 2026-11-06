# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("edc.exo_predictor")

G = 9.797759
ATM = 101231.65625

_STAR_ALIASES = {
    "A": ("A_BlueWhiteSuperGiant",),
    "B": ("B_BlueWhiteSuperGiant",),
    "F": ("F_WhiteSuperGiant",),
    "G": ("G_WhiteSuperGiant",),
    "K": ("K_OrangeGiant",),
    "M": ("M_RedGiant", "M_RedSuperGiant"),
}
_PREFIX_CLASSES = ("D", "C", "W")
_LUM_SUFFIXES = ("a", "b", "ab", "z")


@dataclass(frozen=True)
class BodyPrediction:
    possible: dict[str, list[tuple[str, int]]]
    up_to: int


def load_rules(*paths: Path) -> list[dict] | None:
    for p in paths:
        try:
            if p and p.exists():
                species = json.loads(p.read_text(encoding="utf-8")).get("species")
                if isinstance(species, list) and species:
                    return species
        except Exception:
            log.exception("Failed to load exo habitat rules from %s", p)
    return None


def _atm(s) -> str:
    s = re.sub(r"[^a-z]", "", str(s or "").lower())
    return "" if s == "none" else s


def _star_matches(star: dict, entry) -> bool:
    cls, lum = (entry, None) if isinstance(entry, str) else (entry[0], entry[1])
    st = star.get("StarType") or ""
    if cls in _PREFIX_CLASSES:
        ok = st.startswith(cls)
    else:
        ok = st == cls or st in _STAR_ALIASES.get(cls, ())
    if not ok or lum is None:
        return ok
    sl = star.get("Luminosity") or ""
    return sl == lum or (sl.startswith(lum) and sl[len(lum):] in _LUM_SUFFIXES)


def _any_star(stars, entries) -> bool:
    return any(_star_matches(s, e) for s in stars for e in entries)


def fits(rec: dict, ruleset: dict, stars: dict[int, dict], system_classes: set[str], fss_complete: bool) -> bool:
    gv = rec.get("SurfaceGravity")
    if gv is not None:
        g = gv / G
        if g < ruleset.get("min_gravity_g", g) or g > ruleset.get("max_gravity_g", g):
            return False
    t = rec.get("SurfaceTemperature")
    if t is not None and (t < ruleset.get("min_temp_k", t) or t > ruleset.get("max_temp_k", t)):
        return False
    pa = rec.get("SurfacePressure")
    if pa is not None:
        p = pa / ATM
        if p < ruleset.get("min_pressure_atm", p) or p >= ruleset.get("max_pressure_atm", p + 1):
            return False
    d = rec.get("DistanceLS")
    if d is not None and d < ruleset.get("min_distance_from_arrival_ls", d):
        return False
    op = rec.get("OrbitalPeriod")
    if op is not None and abs(op) > ruleset.get("max_orbital_period_s", abs(op)):
        return False

    if "atmospheres" in ruleset and rec.get("AtmosphereType") is not None:
        if _atm(rec["AtmosphereType"]) not in {_atm(a) for a in ruleset["atmospheres"]}:
            return False
    comp = rec.get("AtmosphereComposition")
    if comp:
        have = {_atm(c.get("Name")): c.get("Percent") or 0 for c in comp}
        for name, pct in (ruleset.get("min_atmosphere_component_pct") or {}).items():
            if have.get(_atm(name), 0) < pct:
                return False

    pc = rec.get("PlanetClass")
    if pc and "body_types" in ruleset and pc.lower() not in {b.lower() for b in ruleset["body_types"]}:
        return False

    vol = rec.get("Volcanism")
    rule = ruleset.get("volcanism")
    if rule is not None and vol is not None:
        vol = vol.lower()
        if vol == "no volcanism":
            vol = ""
        if rule == "none":
            if vol:
                return False
        elif rule in ("required", "any"):
            if not vol:
                return False
        elif isinstance(rule, dict) and not any(s in vol for s in rule.get("contains_any", [])):
            return False

    if fss_complete:
        if "star_anywhere_in_system" in ruleset and stars:
            if not _any_star(stars.values(), ruleset["star_anywhere_in_system"]):
                return False
        if "system_has_body_type" in ruleset:
            if not {c.lower() for c in system_classes} & {b.lower() for b in ruleset["system_has_body_type"]}:
                return False

    if "parent_or_primary_star" in ruleset and stars and rec.get("Parents") is not None:
        parent_ids = [p["Star"] for p in rec["Parents"] if isinstance(p, dict) and "Star" in p]
        if all(i in stars for i in parent_ids):
            cands = [stars[i] for i in parent_ids] + [s for s in stars.values() if s.get("DistanceLS") == 0]
            if cands and not _any_star(cands, ruleset["parent_or_primary_star"]):
                return False
    return True


def predict_body(rec, rules, values, stars, system_classes, fss_complete,
                 known_species: dict[str, str], finished_genera: set[str]) -> BodyPrediction | None:
    signals = rec.get("BioSignals") or 0
    if not rec.get("PlanetClass") or rec.get("SurfaceGravity") is None or signals <= 0:
        return None

    def value(name):
        sv = values.by_species.get(name)
        return sv.base_value if sv else 0

    genera: dict[str, list[tuple[str, int]]] = {}
    for r in rules:
        if any(fits(rec, rs, stars, system_classes, fss_complete) for rs in r["rulesets"]):
            genera.setdefault(r["genus"], []).append((r["species"], value(r["species"])))
    for lst in genera.values():
        lst.sort(key=lambda sv: -sv[1])

    dss = rec.get("BioGenuses")
    if dss:
        genera = {g: v for g, v in genera.items() if g in dss}
        slots = len(dss)
    else:
        slots = signals

    real = [value(sp) for g, sp in known_species.items() if g not in finished_genera]
    taken = len(real) + len(finished_genera)
    remaining = {g: v for g, v in genera.items() if g not in known_species and g not in finished_genera}
    remaining = dict(sorted(remaining.items(), key=lambda kv: -kv[1][0][1]))
    best = [v[0][1] for v in remaining.values()]
    return BodyPrediction(remaining, sum(real) + sum(best[:max(0, slots - taken)]))


def predict_system(state, rules, values, sightings: dict[int, list]) -> dict[str, BodyPrediction]:
    if rules is None or values is None:
        return {}
    stars = getattr(state, "system_stars", {})
    classes = {b["PlanetClass"] for b in state.bodies.values() if b.get("PlanetClass")}

    def genus_of(name):
        sp = (name or "").split(" - ")[0].strip()
        sv = values.by_species.get(sp)
        return (sv.genus, sp) if sv else None

    out = {}
    for name, rec in state.bodies.items():
        bid = rec.get("BodyID")
        known: dict[str, str] = {}
        for s in sorted(sightings.get(bid) or [], key=lambda s: s.get("last_seen") or ""):
            gs = genus_of(s.get("species_name"))
            if gs:
                known[gs[0]] = gs[1]
        finished: set[str] = set()
        for e in state.exo.values():
            if e.get("BodyID") != bid:
                continue
            gs = genus_of(e.get("Species"))
            if gs:
                known[gs[0]] = gs[1]
            if (e.get("Samples") or 0) >= 3 and (gs or e.get("Genus")):
                finished.add(gs[0] if gs else e["Genus"])
        pred = predict_body(rec, rules, values, stars, classes, bool(state.fss_complete), known, finished)
        if pred is not None:
            out[name] = pred
    return out


def possible_text(pred: BodyPrediction) -> str:
    if not pred.possible:
        return ""
    return f"Possible: {', '.join(pred.possible)} · up to {pred.up_to / 1e6:.1f}M"
