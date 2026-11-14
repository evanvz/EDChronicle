from edc.core.colonisation_facilities import by_rc_type, load


def test_known_values():
    d = load()["dodec_starport"]
    assert d["tier"] == 3 and d["cp_cost"]["t3"] == 6 and d["score"] == 15
    assert d["effects"]["sec"] == -4 and d["haul"] == 236000
    assert load()["coriolis_starport"]["cp_reward"]["t3"] == 1
    assert "mining_industrial_installation" in load()["industrial_hub"]["requires"]
    assert load()["refinery_hub"]["location"] == "surface"


def test_every_rc_type_maps():
    assert by_rc_type("dual_truss")["name"] == "Coriolis Starport"
    assert by_rc_type("silenus")["name"] == "Hub > Refinery"
    assert by_rc_type("nope") is None


def test_ports_flagged():
    assert {k for k, v in load().items() if v["port"]} == {
        "coriolis_starport", "asteroid_starport", "orbis_starport",
        "ocellus_starport", "dodec_starport", "large_planetary_port"}
