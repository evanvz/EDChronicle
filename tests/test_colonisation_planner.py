from edc.core import colonisation_facilities
from edc.core.colonisation_planner import plan, port_cost, slot_table

_COLS = ("name", "sub_type", "landable", "cluster", "economies", "rings", "orbital_slots", "surface_slots", "ground_slots")


def _system(name, rows):
    return {"name": name, "bodies": [dict(zip(_COLS, (f"{name} {r[0]}".strip(),) + r[1:]), body_id=i)
                                     for i, r in enumerate(rows)]}


# hand-written, shaped like ICZ DR-M b7-1: 9 orbital, 14 surface known slots, two clusters plus the star
DRM = "ICZ DR-M b7-1"
DRM_SYS = _system(DRM, [
    ("A", "K Star", None, None, [], False, 2, 0, 0),
    ("1", "High metal content world", True, 1, ["Refinery", "Extraction"], True, 3, 4, 4),
    ("1 a", "Rocky body", True, 1, ["Refinery"], False, None, None, 4),          # orbital from Raven, surface est
    ("1 b", "Rocky body", True, 1, ["Extraction", "Refinery", "Terraforming"], False, 1, 3, 3),
    ("2", "Icy body", True, 2, ["Industrial"], False, 2, 3, 3),
])
DRM_RAVEN = {f"{DRM} 1 a": (1, None)}
DRM_PRIMARY = f"{DRM} 1"

# hand-written, shaped like Col 359 Sector LC-T d4-17 (larger): 19 orbital, 37 surface known slots, three clusters
LCT = "Col 359 Sector LC-T d4-17"
LCT_SYS = _system(LCT, [
    ("A", "F Star", None, None, [], False, 3, 0, 0),
    ("1", "Class II gas giant", False, 1, ["HighTech", "Industrial"], True, 4, 0, 0),
    ("1 a", "Rocky body", True, 1, ["Industrial"], False, 1, 5, 5),
    ("1 b", "Icy body", True, 1, ["Industrial", "HighTech"], False, 1, 4, 4),
    ("1 c", "Icy body", True, 1, ["Industrial"], False, 1, 3, 3),
    ("2", "High metal content world", True, 2, ["Extraction", "Refinery"], False, 3, 6, 6),
    ("2 a", "Rocky body", True, 2, ["Extraction"], False, 1, 4, 4),
    ("3", "Earth-like world", False, 3, ["Agriculture", "Tourism", "Terraforming"], True, 3, 0, 0),
    ("3 a", "Rocky body", True, 3, ["Agriculture"], False, 1, 8, 8),
    ("3 b", "Rocky body", True, 3, ["Agriculture", "Extraction"], False, 1, 7, 7),
])
LCT_PRIMARY = f"{LCT} 1"

FAC = colonisation_facilities.load()


def _drm(kind, group=False, system=DRM_SYS, raven=DRM_RAVEN):
    return plan(system, slot_table(system, raven), DRM_PRIMARY, group, kind)


def _with(system, name, **kw):
    return {**system, "bodies": [{**b, **kw} if b["name"] == name else b for b in system["bodies"]]}


def test_port_cost_ramp():
    assert [port_cost(2, n) for n in range(1, 6)] == [3, 3, 5, 7, 9]
    assert [port_cost(3, n) for n in range(1, 6)] == [6, 6, 12, 18, 24]


def test_slot_sources_order():
    body = {"name": "X 1", "orbital_slots": None, "surface_slots": 5, "ground_slots": 4}
    row = lambda b, raven: slot_table({"bodies": [b]}, raven)[0]
    r = row(body, {"X 1": (None, 3)})
    assert (r["surface"], r["surface_source"]) == (5, "entered")
    assert (r["orbital"], r["orbital_source"]) == (None, None)
    r = row({**body, "surface_slots": None}, {"X 1": (None, 3)})
    assert (r["surface"], r["surface_source"]) == (3, "raven")
    r = row({**body, "surface_slots": None}, None)
    assert (r["surface"], r["surface_source"]) == (4, "est")
    # older payloads lack the entered keys
    r = row({"name": "X 1", "ground_slots": None}, None)
    assert (r["orbital"], r["orbital_source"], r["surface"], r["surface_source"]) == (None, None, None, None)


def test_unknown_orbital_never_used():
    name = f"{DRM} 2"
    p = _drm("full", system=_with(DRM_SYS, name, orbital_slots=None))
    assert not any(s["body"] == name and s["location"] == "orbital" for s in p["steps"])
    assert name in p["unknown"]
    assert f"orbital slots unknown: {name}" in p["warnings"]


def test_service_t3_primary_no_steps():
    p = _drm("service", group=True)
    assert (p["steps"][0]["title"], p["steps"][0]["note"]) == ("Primary: Ocellus", "free")
    assert p["note"] == "Tier 3 primary: all services from the start"


def test_service_t3_primary_secures():
    p = _drm("service", group=True)
    assert p["outcome"]["stats"]["sec"] >= 0 or "security below 0 after the plan" in p["warnings"]
    assert {s["facility"] for s in p["steps"][1:]} <= {"relay_installation", "security_installation",
                                                       "military_settlement_medium"}


def test_refinery_low_sec_warns():
    p = _drm("refinery")
    assert p["outcome"]["stats"]["sec"] < 0
    assert "security below 0 after the plan" in p["warnings"]


def test_refinery_third_economy_warns():
    p = _drm("refinery", system=_with(DRM_SYS, DRM_PRIMARY, economies=["HighTech", "Industrial"]))
    assert any(w.startswith("1 market: ") and "Refinery" in w and "cannibalised" in w for w in p["warnings"])
    assert not any("market:" in w for w in _drm("service")["warnings"])


def test_five_at_once_note_every_type():
    for kind in ("refinery", "service", "full"):
        assert "Up to 5 facilities can be under construction at once" in _drm(kind)["warnings"]


def test_service_t2_adds_comms_on_primary():
    p = _drm("service")
    assert [(s["facility"], s["body"], s["location"]) for s in p["steps"]] == [
        ("coriolis_starport", DRM_PRIMARY, "orbital"), ("comms_installation", DRM_PRIMARY, "orbital")]


def test_service_stop_no_link_slot_warns():
    p = _drm("service", system=_with(DRM_SYS, DRM_PRIMARY, orbital_slots=1))   # the Coriolis takes the only one
    assert [s["facility"] for s in p["steps"]] == ["coriolis_starport"]
    assert "no free orbital slot on the primary body for the Cartographics/Vista link" in p["warnings"]


def test_refinery_hub_on_primary_surface():
    p = _drm("refinery")
    keys = [(s["facility"], s["body"], s["location"]) for s in p["steps"]][1:]   # after the primary
    assert keys[0] == ("comms_installation", DRM_PRIMARY, "orbital")
    assert keys[1] == ("refinery_hub", DRM_PRIMARY, "surface")
    assert keys[2][0] in ("mining_settlement_large", "mining_settlement_medium") and keys[2][1] == DRM_PRIMARY


def test_refinery_no_surface_warns():
    p = _drm("refinery", system=_with(DRM_SYS, DRM_PRIMARY, surface_slots=0))
    assert "no surface slot on the primary body: no Refinery Hub" in p["warnings"]
    assert all(s["facility"] != "refinery_hub" for s in p["steps"])


def _check_full(p):
    assert p["unused"] == {"orbital": 0, "surface": 0}
    assert all(s["t2"] >= 0 and s["t3"] >= 0 for s in p["steps"])
    for i, s in enumerate(p["steps"]):
        req = FAC[s["facility"]]["requires"]
        assert not req or any(x["facility"] in req for x in p["steps"][:i]), s
    assert any(FAC[s["facility"]]["port"] and FAC[s["facility"]]["tier"] == 3 for s in p["steps"][1:])
    assert p["steps"][0]["note"] == "free" and p["steps"][0]["title"].startswith("Primary: ")
    assert all(s["haul"] == FAC[s["facility"]]["haul"] for s in p["steps"])
    assert sum(s["haul"] for s in p["steps"]) == p["outcome"]["haul"]


def test_full_build_dr_m_shape():
    _check_full(_drm("full"))
    assert len(_drm("full")["steps"]) == 23   # the real DR-M b7-1 build: 23 facilities incl. the primary
    _check_full(_drm("full", group=True))


def test_full_build_places_cluster_hub():
    p = _drm("full")
    _check_full(p)
    assert any(s["facility"].endswith("_hub") for s in p["steps"])
    assert sum(FAC[s["facility"]]["port"] and FAC[s["facility"]]["tier"] == 3 for s in p["steps"][1:]) >= 2


def test_full_build_hightech_fills_surface():
    # one HighTech body, no orbital slot left after the Coriolis: no T2 for bio settlements
    sys = _system("HT", [("1", "Rocky body", True, 1, ["HighTech"], False, 1, 6, 6)])
    p = plan(sys, slot_table(sys, None), "HT 1", False, "full")
    assert p["unused"]["surface"] == 0
    assert any(s["facility"] == "scientific_surface_outpost" for s in p["steps"])
    assert all(s["t2"] >= 0 and s["t3"] >= 0 for s in p["steps"])


def test_full_build_lc_t_shape():
    _check_full(plan(LCT_SYS, slot_table(LCT_SYS, None), LCT_PRIMARY, False, "full"))


def test_full_build_final_sec_warning_matches():
    tour = _system("TR", [("1", "Earth-like world", True, 1, ["Tourism"], False, 2, 8, 8),
                          ("1 a", "Rocky body", True, 1, ["Tourism"], False, 1, 6, 6)])
    plans = [plan(tour, slot_table(tour, None), "TR 1", g, "full") for g in (False, True)]
    plans += [_drm("full", group=g) for g in (False, True)]
    plans += [plan(LCT_SYS, slot_table(LCT_SYS, None), LCT_PRIMARY, g, "full") for g in (False, True)]
    plans += [_drm(k, group=g) for k in ("service", "refinery") for g in (False, True)]
    for p in plans:
        assert ("security below 0 after the plan" in p["warnings"]) == (p["outcome"]["stats"]["sec"] < 0)


def test_primary_free_and_not_ramped():
    p = _drm("full", group=True)
    assert p["steps"][0]["facility"] == "ocellus_starport"
    assert p["steps"][0]["t3"] == FAC["ocellus_starport"]["cp_reward"]["t3"]   # free: its reward, no cost
    i = next(i for i, s in enumerate(p["steps"]) if i and FAC[s["facility"]]["port"])
    assert FAC[p["steps"][i]["facility"]]["tier"] == 3
    assert p["steps"][i - 1]["t3"] - p["steps"][i]["t3"] == 6


def test_outcome_sums():
    p = _drm("service", system=_with(DRM_SYS, DRM_PRIMARY, orbital_slots=1))
    c = FAC["coriolis_starport"]
    assert p["outcome"] == {"stats": c["effects"], "haul": 63001, "score": 8}
