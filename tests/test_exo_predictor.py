# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from edc.core.exo_predictor import BodyPrediction, fits, load_rules, possible_text, predict_body, predict_system
from edc.core.exo_values import ExoValueTable

ROOT = Path(__file__).resolve().parent.parent
HABITAT = ROOT / "settings" / "exo_habitat.json"
VALUES = ROOT / "settings" / "exo_values.json"
RULES = load_rules(HABITAT)
TABLE = ExoValueTable.load_from_paths(VALUES)


def ruleset(name, i=0):
    return next(r for r in RULES if r["species"] == name)["rulesets"][i]


def body(**kw):
    rec = {"BodyID": 5, "PlanetClass": "Rocky body", "SurfaceGravity": 1.0, "SurfaceTemperature": 177.0,
           "SurfacePressure": 2000.0, "AtmosphereType": "CarbonDioxide", "Volcanism": "", "BioSignals": 2}
    rec.update(kw)
    return rec


def fit(rec, rs, stars=None, classes=(), fss=False):
    return fits(rec, rs, stars or {}, set(classes), fss)


def fake_values(table):
    return SimpleNamespace(by_species={n: SimpleNamespace(base_value=v, genus=g) for n, (g, v) in table.items()})


def fake_rules(table):
    return [{"genus": g, "species": n, "rulesets": [{}]} for n, (g, v) in table.items()]


def test_data_file_every_species_has_a_value():
    assert len(RULES) == 118
    assert [r["species"] for r in RULES if r["species"] not in TABLE.by_species] == []


def test_missing_or_corrupt_file_returns_none(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert load_rules(tmp_path / "missing.json") is None
    assert load_rules(bad) is None


def test_aleoida_arcus_fits():
    assert fit(body(), ruleset("Aleoida Arcus"))


@pytest.mark.parametrize("change", [
    {"SurfaceGravity": 5.0}, {"SurfaceTemperature": 300.0}, {"SurfacePressure": 10.0},
    {"AtmosphereType": "Argon"}, {"PlanetClass": "Icy body"}, {"Volcanism": "minor rocky magma volcanism"},
])
def test_each_bound_excludes(change):
    assert not fit(body(**change), ruleset("Aleoida Arcus"))


def test_max_pressure_is_exclusive():
    rs = {"max_pressure_atm": 0.5}
    assert fit(body(SurfacePressure=0.49 * 101231.65625), rs)
    assert not fit(body(SurfacePressure=0.5 * 101231.65625), rs)


def test_missing_value_skips_that_test():
    assert fit(body(SurfaceTemperature=None), ruleset("Aleoida Arcus"))


@pytest.mark.parametrize("spelling", ["CarbonDioxide", "Carbon dioxide", "carbon dioxide"])
def test_atmosphere_spellings(spelling):
    assert fit(body(AtmosphereType=spelling), {"atmospheres": ["CarbonDioxide"]})


@pytest.mark.parametrize("none", ["", "None"])
def test_no_atmosphere_spellings(none):
    assert fit(body(AtmosphereType=none), {"atmospheres": ["None"]})
    assert not fit(body(AtmosphereType=none), {"atmospheres": ["Argon"]})


@pytest.mark.parametrize("v", ["", "No volcanism"])
def test_no_volcanism_spellings(v):
    assert fit(body(Volcanism=v), {"volcanism": "none"})
    assert not fit(body(Volcanism=v), {"volcanism": "required"})
    assert not fit(body(Volcanism=v), {"volcanism": {"contains_any": ["magma"]}})


def test_volcanism_contains_any():
    rs = {"volcanism": {"contains_any": ["magma"]}}
    assert fit(body(Volcanism="Minor Rocky Magma Volcanism"), rs)
    assert not fit(body(Volcanism="minor water geysers volcanism"), rs)


def test_star_anywhere_only_after_fss_complete():
    stars = {1: {"StarType": "M", "Luminosity": "V", "DistanceLS": 0}}
    rs = {"star_anywhere_in_system": ["O"]}
    assert fit(body(), rs, stars, fss=False)
    assert not fit(body(), rs, stars, fss=True)
    assert fit(body(), rs, {}, fss=True)


def test_system_body_type_only_after_fss_complete():
    rs = {"system_has_body_type": ["Earthlike body"]}
    assert fit(body(), rs, classes=["Rocky body"], fss=False)
    assert not fit(body(), rs, classes=["Rocky body"], fss=True)
    assert fit(body(), rs, classes=["Rocky body", "Earthlike body"], fss=True)


def test_parent_star_needs_every_parent_scanned():
    rs = {"parent_or_primary_star": ["O"]}
    stars = {1: {"StarType": "M", "Luminosity": "V", "DistanceLS": 0}}
    rec = body(Parents=[{"Star": 1}, {"Star": 2}])
    assert fit(rec, rs, stars)
    stars[2] = {"StarType": "K", "Luminosity": "V", "DistanceLS": 50}
    assert not fit(rec, rs, stars)
    stars[2]["StarType"] = "O"
    assert fit(rec, rs, stars)


def test_parent_star_primary_counts():
    rs = {"parent_or_primary_star": ["O"]}
    stars = {1: {"StarType": "O", "Luminosity": "V", "DistanceLS": 0}, 2: {"StarType": "M", "DistanceLS": 90}}
    assert fit(body(Parents=[{"Star": 2}]), rs, stars)


@pytest.mark.parametrize("rule,star,ok", [
    (["A"], "A_BlueWhiteSuperGiant", True), (["A"], "A", True), (["A"], "AeBe", False),
    (["D"], "DA", True), (["M"], "M_RedSuperGiant", True), (["K"], "K_OrangeGiant", True),
    (["MS"], "M", False), (["F"], "F_WhiteSuperGiant", True),
    ([["B", "IV"]], ("B", "IVab"), True), ([["B", "IV"]], ("B", "V"), False),
    ([["B", "I"]], ("B", "II"), False), ([["B", "I"]], ("B", "Iab"), True),
])
def test_star_class_and_luminosity_matching(rule, star, ok):
    cls, lum = star if isinstance(star, tuple) else (star, "V")
    stars = {1: {"StarType": cls, "Luminosity": lum, "DistanceLS": 0}}
    assert fit(body(), {"star_anywhere_in_system": rule}, stars, fss=True) is ok


def test_untested_rule_types_pass():
    rs = {"regions": ["!center"], "region_ids": {"in": [1], "not_in": None}, "nebula": "all",
          "near_guardian_ruins": True, "tuber_zones": ["x"], "system": "HIP 87621"}
    assert fit(body(), rs)


def test_distance_orbital_period_and_composition():
    assert not fit(body(DistanceLS=100), {"min_distance_from_arrival_ls": 2000})
    assert fit(body(DistanceLS=2500), {"min_distance_from_arrival_ls": 2000})
    assert fit(body(DistanceLS=None), {"min_distance_from_arrival_ls": 2000})
    assert not fit(body(OrbitalPeriod=-100000), {"max_orbital_period_s": 86400})
    assert fit(body(OrbitalPeriod=-80000), {"max_orbital_period_s": 86400})
    rs = {"min_atmosphere_component_pct": {"SulphurDioxide": 1.05}}
    assert fit(body(AtmosphereComposition=[{"Name": "SulphurDioxide", "Percent": 2.0}]), rs)
    assert not fit(body(AtmosphereComposition=[{"Name": "CarbonDioxide", "Percent": 99.0}]), rs)
    assert fit(body(AtmosphereComposition=[]), rs)


def test_no_facts_no_prediction():
    rules, vals = fake_rules({"X One": ("X", 5)}), fake_values({"X One": ("X", 5)})
    for rec in (body(PlanetClass=""), body(SurfaceGravity=None), body(BioSignals=0)):
        assert predict_body(rec, rules, vals, {}, set(), False, {}, set()) is None


GEN = {"X One": ("X", 10), "X Two": ("X", 4), "Y One": ("Y", 7), "Z One": ("Z", 3)}


def pb(rec, known=None, finished=(), table=GEN):
    return predict_body(rec, fake_rules(table), fake_values(table), {}, set(), False, known or {}, set(finished))


def test_up_to_top_n_genera():
    p = pb(body(BioSignals=2))
    assert p.up_to == 17
    assert list(p.possible) == ["X", "Y", "Z"]
    assert p.possible["X"] == [("X One", 10), ("X Two", 4)]


def test_more_signals_than_genera():
    assert pb(body(BioSignals=5), table={"X One": ("X", 10), "Y One": ("Y", 7)}).up_to == 17


def test_dss_limits_to_found_genera():
    p = pb(body(BioSignals=2, BioGenuses=["X"]))
    assert list(p.possible) == ["X"]
    assert p.up_to == 10


def test_known_species_uses_real_value_and_a_slot():
    t = dict(GEN, **{"X Big": ("X", 1_000_000)})
    p = pb(body(BioSignals=2), known={"X": "X Big"}, table=t)
    assert p.up_to == 1_000_007
    assert "X" not in p.possible


def test_known_species_up_to():
    assert pb(body(BioSignals=2), known={"X": "X Two"}).up_to == 4 + 7


def test_finished_genus_takes_slot_counts_zero():
    p = pb(body(BioSignals=2), finished={"X"})
    assert p.up_to == 7
    assert "X" not in p.possible


def test_all_finished_up_to_zero():
    p = pb(body(BioSignals=3), finished={"X", "Y", "Z"})
    assert p.possible == {} and p.up_to == 0 and possible_text(p) == ""


def state(bodies, exo=None, fss=False, stars=None):
    return SimpleNamespace(bodies=bodies, exo=exo or {}, fss_complete=fss, system_stars=stars or {})


def test_predict_system_sampled_beats_sighting():
    st = state({"A 1": body(BioSignals=1)}, {"k": {"BodyID": 5, "Genus": "X", "Species": "X Two", "Samples": 1}})
    out = predict_system(st, fake_rules(GEN), fake_values(GEN),
                         {5: [{"species_name": "X One", "last_seen": "2026-01-01"}]})
    assert out["A 1"].up_to == 4
    assert "X" not in out["A 1"].possible


def test_predict_system_bad_names_ignored():
    st = state({"A 1": body(BioSignals=1)})
    sight = {5: [{"species_name": "Nonsense", "last_seen": "1"},
                 {"species_name": "Stratum Tectonicas - Teal", "last_seen": "2"}]}
    out = predict_system(st, RULES, TABLE, sight)
    assert "Stratum" not in out["A 1"].possible
    assert out["A 1"].up_to == TABLE.by_species["Stratum Tectonicas"].base_value


def test_predict_system_finished_from_samples():
    st = state({"A 1": body(BioSignals=1)}, {"k": {"BodyID": 5, "Genus": "X", "Species": "X One", "Samples": 3}})
    assert predict_system(st, fake_rules(GEN), fake_values(GEN), {})["A 1"].up_to == 0


def test_predict_system_skips_no_bio_bodies():
    st = state({"A 1": body(BioSignals=0), "A 2": body(BodyID=6, BioSignals=1)})
    assert list(predict_system(st, fake_rules(GEN), fake_values(GEN), {})) == ["A 2"]


def test_predict_system_none_inputs():
    assert predict_system(state({}), None, fake_values(GEN), {}) == {}
    assert predict_system(state({}), fake_rules(GEN), None, {}) == {}


def test_guesses_not_written_to_state():
    st = state({"A 1": body(BioSignals=2)}, {"k": {"BodyID": 5, "Genus": "X", "Species": "X One", "Samples": 1}})
    st.bio_genuses = {"A 1": ["X"]}
    before = copy.deepcopy((st.bodies, st.bio_genuses, st.exo))
    predict_system(st, fake_rules(GEN), fake_values(GEN), {5: [{"species_name": "Y One", "last_seen": "1"}]})
    assert (st.bodies, st.bio_genuses, st.exo) == before


def test_possible_text():
    p = BodyPrediction({"Aleoida": [("a", 12_300_000)], "Bacterium": [("b", 1)]}, 12_300_000)
    assert possible_text(p) == "Possible: Aleoida, Bacterium · up to 12.3M"


def test_equals_any_volcanism_blatteum():
    rs = next(r for r in RULES if r["species"] == "Blatteum Sinuous Tubers")["rulesets"]
    vol = [x for x in rs if "equals_any" in (x.get("volcanism") or {})][0]
    assert fit(body(Volcanism="Rocky magma volcanism"), {"volcanism": vol["volcanism"]})
    assert fit(body(Volcanism="major silicate vapour geysers"), {"volcanism": vol["volcanism"]})
    assert not fit(body(Volcanism="minor rocky magma volcanism"), {"volcanism": vol["volcanism"]})


def test_plural_journal_genus_names():
    t = {"Brain Tree One": ("Brain Tree", 5), "X One": ("X", 9)}
    p = pb(body(BioSignals=2, BioGenuses=["Brain Trees"]), table=t)
    assert list(p.possible) == ["Brain Tree"]
    p = pb(body(BioSignals=1), finished={"Brain Trees"}, table=t)
    assert p.up_to == 0 and "Brain Tree" not in p.possible
    st = state({"A 1": body(BioSignals=1)}, {"k": {"BodyID": 5, "Genus": "Brain Trees", "Species": "", "Samples": 3}})
    assert predict_system(st, fake_rules(t), fake_values(t), {})["A 1"].up_to == 0
