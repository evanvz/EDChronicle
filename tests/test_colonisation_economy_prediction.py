"""_predict_economies() -- Update 3 body-attribute economy override table,
verbatim from Frontier's patch notes. Pure function, no Qt needed. Body
class strings confirmed live against real Spansh data (see
colonisation_panel.py's own comments for the exact wording variants:
"Earth-like world", "High metal content world", "Metal-rich body",
"Rocky Ice world", "Rocky body", "Icy body", star subtypes)."""
from edc.ui.panels.colonisation_panel import _predict_economies


def test_earth_like_world():
    assert _predict_economies("Earth-like world", False) == ["Agriculture", "High Tech", "Military", "Tourism"]


def test_water_world():
    assert _predict_economies("Water world", False) == ["Agriculture", "Tourism"]


def test_ammonia_world():
    assert _predict_economies("Ammonia world", False) == ["High Tech", "Tourism"]


def test_gas_giant():
    assert _predict_economies("Class II gas giant", False) == ["High Tech", "Industrial"]


def test_metal_rich_body():
    assert _predict_economies("Metal-rich body", False) == ["Extraction"]


def test_high_metal_content_world():
    assert _predict_economies("High metal content world", False) == ["Extraction"]


def test_rocky_ice_not_misclassified_as_plain_rocky():
    assert _predict_economies("Rocky Ice world", False) == ["Industrial", "Refinery"]


def test_rocky_body():
    assert _predict_economies("Rocky body", False) == ["Refinery"]


def test_icy_body():
    assert _predict_economies("Icy body", False) == ["Industrial"]


def test_neutron_star():
    assert _predict_economies("Neutron Star", False) == ["High Tech", "Tourism"]


def test_white_dwarf_star():
    assert _predict_economies("White Dwarf (DA) Star", False) == ["High Tech", "Tourism"]


def test_black_hole():
    assert _predict_economies("Black Hole", False) == ["High Tech", "Tourism"]


def test_ordinary_star_no_economy():
    assert _predict_economies("G (White-Yellow) Star", False) == []


def test_rings_add_extraction_on_top_of_base_class():
    assert _predict_economies("Icy body", True) == ["Industrial", "Extraction"]


def test_rings_alone_on_a_body_with_no_other_match():
    assert _predict_economies("G (White-Yellow) Star", True) == ["Extraction"]


def test_rings_not_duplicated_when_already_extraction():
    assert _predict_economies("Metal-rich body", True) == ["Extraction"]


def test_blank_planet_class_no_rings():
    assert _predict_economies("", False) == []


def test_none_planet_class_does_not_raise():
    assert _predict_economies(None, False) == []
