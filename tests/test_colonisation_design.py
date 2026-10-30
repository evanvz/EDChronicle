from edc.core.colonisation_design import plan_system

SYS = "Tucanae Sector PY-R b4-1"
_COLS = ("name", "sub_type", "landable", "distance_ls", "port_types", "economies", "body_id", "parent_id", "cluster",
         "rings", "ground_slots", "terraformable", "geo", "bio")
OI, OS = ["Orbital"], ["Orbital", "Surface"]
# hub /api/colonisation-system shape; values from the hub's Tucanae fixture (Spansh dump)
_ROWS = [
    ("", "M (Red dwarf) Star", None, 0, ["Orbital", "Asteroid"], ["Extraction", "Military"], 0, None, None, True, 0, False, False, False),
    ("1", "High metal content world", False, 125, OI, ["Extraction"], 5, 0, 5, False, 0, False, False, False),
    ("2", "Icy body", False, 225, OI, ["Industrial"], 6, 0, 6, False, 0, False, False, False),
    ("3 f", "Icy body", True, 891, OS, ["Agriculture", "Industrial", "Terraforming"], 15, 7, 7, False, 3, False, False, True),
    ("3 a", "Icy body", True, 897, OS, ["Extraction", "Industrial"], 9, 7, 7, False, 2, False, True, False),
    ("3 d", "Icy body", True, 897, OS, ["Agriculture", "Industrial", "Terraforming"], 12, 7, 7, False, 3, False, False, True),
    ("3", "Class I gas giant", False, 898, ["Orbital", "Asteroid"], ["Extraction", "HighTech", "Industrial"], 7, 0, 7, True, 0, False, False, False),
    ("3 b", "Icy body", True, 899, OS, ["Industrial"], 10, 7, 7, False, 1, False, False, False),
    ("3 c", "Icy body", True, 900, OS, ["Industrial"], 11, 7, 7, False, 1, False, False, False),
    ("3 e", "Icy body", True, 905, OS, ["Agriculture", "Industrial", "Terraforming"], 13, 7, 7, False, 3, False, False, True),
    ("4 c", "Icy body", True, 1192, OS, ["Industrial"], 33, 28, 28, False, 1, False, False, False),
    ("4", "Class I gas giant", False, 1196, OI, ["HighTech", "Industrial"], 28, 0, 28, False, 0, False, False, False),
    ("4 a", "Icy body", True, 1196, OS, ["Industrial"], 29, 28, 28, False, 1, False, False, False),
    ("4 a a", "Icy body", True, 1196, OS, ["Extraction", "Industrial"], 30, 29, 29, False, 2, False, True, False),
    ("4 d", "Icy body", True, 1196, OS, ["Industrial"], 34, 28, 28, False, 1, False, False, False),
    ("4 b", "Icy body", True, 1197, OS, ["Industrial"], 31, 28, 28, False, 1, False, False, False),
    ("5", "Icy body", False, 1721, OI, ["Industrial"], 35, 0, 35, False, 0, False, False, False),
    ("5 a", "Icy body", True, 1721, OS, ["Industrial"], 36, 35, 35, False, 1, False, False, False),
]
TUC = {"name": SYS, "main_star": "M (Red dwarf) Star", "service_score": 83,
       "service_reason": "Gas giant 3 at 898 ls: 6 landable moons, ~13 ground slots, rings; Industrial + Agriculture",
       "bodies": [dict(zip(_COLS, (f"{SYS} {r[0]}".strip(),) + r[1:])) for r in _ROWS]}


def test_star_primary_is_poor():
    assert plan_system(TUC, "Tucanae Sector PY-R b4-1", False)["poor"].startswith("Primary slot on a star")


def test_solo_plan_on_gas_giant_3():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", False)
    assert p["poor"] is None
    assert [s["title"] for s in p["steps"]][:2] == ["Primary: Coriolis", "Comms installation"]
    assert "Universal Cartographics" in p["steps"][1]["unlocks"] and "Vista Genomics" in p["steps"][1]["unlocks"]


def test_group_plan_skips_comms_step():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", True)
    assert p["steps"][0]["title"] == "Primary: Ocellus"          # rings on body 3
    assert all(s["title"] != "Comms installation" for s in p["steps"])


def test_high_tech_goes_to_other_cluster():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", False)
    ht = next(s for s in p["steps"] if s["title"] == "High Tech Hub")
    assert ht["body"].startswith("Tucanae Sector PY-R b4-1 4")   # cluster 4, not the primary's


def test_missing_body_details_says_so():
    assert plan_system({"bodies": [{"name": "A"}]}, "A", False)["poor"] == "Hub has no body details yet"


def test_no_high_tech_elsewhere_leaves_it_out_with_note():
    sys = {**TUC, "bodies": [{**b, "economies": [e for e in b["economies"] if e != "HighTech"]} if b["cluster"] == 28 else b
                             for b in TUC["bodies"]]}
    p = plan_system(sys, "Tucanae Sector PY-R b4-1 3", False)
    assert all(s["title"] != "High Tech Hub" for s in p["steps"])
    assert "outfitting stock stays at the default" in p["note"]


def test_note_when_hub_best_cluster_differs():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 4", False)
    assert p["poor"] is None and "best cluster is Gas giant 3" in p["note"]
    assert plan_system(TUC, "Tucanae Sector PY-R b4-1 3", False)["note"] is None


def test_planet_without_moons_is_poor():
    assert plan_system(TUC, "Tucanae Sector PY-R b4-1 1", False)["poor"].startswith("No landable moon")


def test_not_reimported_yet_says_no_details():
    sys = {**TUC, "service_score": None, "bodies": [{**b, "cluster": None, "ground_slots": None} for b in TUC["bodies"]]}
    assert plan_system(sys, "Tucanae Sector PY-R b4-1 3", False)["poor"] == "Hub has no body details yet"


def test_unknown_moon_slots_is_not_a_verdict():
    sys = {**TUC, "bodies": [{**b, "ground_slots": None} if b["cluster"] == 7 and b["landable"] else b for b in TUC["bodies"]]}
    assert plan_system(sys, "Tucanae Sector PY-R b4-1 3", False)["poor"].startswith("Ground slots unknown")


def test_landable_primary_with_unknown_slots_keeps_surface_step():
    sys = {**TUC, "bodies": [{**b, "ground_slots": None} if b["name"].endswith(" 3 a") else b for b in TUC["bodies"]]}
    s = next(s for s in plan_system(sys, "Tucanae Sector PY-R b4-1 3 a", False)["steps"] if s["title"].startswith("Surface port"))
    assert "slots unknown" in s["needs"]


def test_missing_distance_is_unknown_not_zero():
    sys = {**TUC, "bodies": [{**b, "distance_ls": None} if b["name"].endswith(" 5") else b for b in TUC["bodies"]]}
    p = plan_system(sys, "Tucanae Sector PY-R b4-1 5", False)
    assert p["poor"] is None and any("distance unknown" in w for w in p["warnings"])


def test_nameless_cluster_root_does_not_raise():
    s = {**TUC, "bodies": [dict(b, name=None) if b["body_id"] == 7 else b for b in TUC["bodies"]]}
    assert plan_system(s, f"{SYS} 4", False)["poor"] is None
