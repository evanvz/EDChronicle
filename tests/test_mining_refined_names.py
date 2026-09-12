"""edc.engine.handlers.mining.handle() -- MiningRefined's Type field is the
raw internal symbol (e.g. "$lepidolite_name;"), not a display name.
Confirmed live: showing it directly rendered as "$Lepidolite_Name;" once
the UI's .title() call ran over the unstripped raw token. Type_Localised
carries the real display name and must be preferred. Same fix applies to
ProspectedAsteroid's Content/Materials[].Name/MotherlodeMaterial."""
from types import SimpleNamespace

from edc.core.state import GameState
from edc.engine.handlers.mining import handle


def _engine():
    return SimpleNamespace(state=GameState())


def test_mining_refined_prefers_localised_type():
    engine = _engine()
    handle(engine, "MiningRefined", {"Type": "$lepidolite_name;", "Type_Localised": "Lepidolite"}, [])
    assert engine.state.mining_refined_totals == {"lepidolite": 1}


def test_mining_refined_falls_back_to_raw_type_if_localised_missing():
    engine = _engine()
    handle(engine, "MiningRefined", {"Type": "$lepidolite_name;"}, [])
    assert engine.state.mining_refined_totals == {"$lepidolite_name;": 1}


def test_mining_refined_accumulates_across_events():
    engine = _engine()
    handle(engine, "MiningRefined", {"Type": "$lepidolite_name;", "Type_Localised": "Lepidolite"}, [])
    handle(engine, "MiningRefined", {"Type": "$lepidolite_name;", "Type_Localised": "Lepidolite"}, [])
    handle(engine, "MiningRefined", {"Type": "$osmium_name;", "Type_Localised": "Osmium"}, [])
    assert engine.state.mining_refined_totals == {"lepidolite": 2, "osmium": 1}


def test_prospected_asteroid_prefers_localised_content():
    engine = _engine()
    handle(engine, "ProspectedAsteroid", {
        "Content": "$AsteroidMaterialContent_High;", "Content_Localised": "Material Content: High",
        "Materials": [], "MotherlodeMaterial": "$Alexandrite_Name;",
        "MotherlodeMaterial_Localised": "Alexandrite",
    }, [])
    assert engine.state.mining_last_prospect_content == "Material Content: High"
    assert engine.state.mining_last_motherlode_material == "Alexandrite"


def test_prospected_asteroid_materials_prefer_localised_names():
    engine = _engine()
    handle(engine, "ProspectedAsteroid", {
        "Materials": [
            {"Name": "lepidolite", "Name_Localised": "Lepidolite", "Proportion": 23.9},
            {"Name": "gold", "Proportion": 14.0},  # no Name_Localised -- falls back to Name
        ],
    }, [])
    names = [m["Name"] for m in engine.state.mining_last_prospect_materials]
    assert names == ["Lepidolite", "gold"]
