"""_current_system_summary() -- the Colonisation tab's one-line "Current
System" card. Occupied/Unoccupied comes from state.population (real live
journal data, not a guess); economy is the real state.system_economy when
occupied, or the same body-attribute prediction the candidate dialog uses
when unoccupied (an uninhabited system has no real economy to report).
Pure function, no Qt needed."""
from types import SimpleNamespace

from edc.ui.panels.colonisation_panel import _current_system_summary


def _state(**overrides):
    defaults = dict(
        system="Test System", population=None,
        system_economy=None, system_economy_secondary=None, bodies={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_no_current_system_returns_none():
    assert _current_system_summary(_state(system=None)) is None


def test_occupied_system_shows_real_economy():
    state = _state(population=5000, system_economy="$economy_Agri;", system_economy_secondary="$economy_HighTech;")
    name, occupied_text, color, economy_text = _current_system_summary(state)
    assert name == "Test System"
    assert occupied_text == "Occupied"
    assert economy_text == "Agri / High Tech"


def test_occupied_system_no_secondary_economy():
    state = _state(population=100, system_economy="$economy_Extraction;", system_economy_secondary="")
    _, _, _, economy_text = _current_system_summary(state)
    assert economy_text == "Extraction"


def test_occupied_system_same_primary_and_secondary_not_duplicated():
    state = _state(population=100, system_economy="$economy_Extraction;", system_economy_secondary="$economy_Extraction;")
    _, _, _, economy_text = _current_system_summary(state)
    assert economy_text == "Extraction"


def test_unoccupied_system_predicts_from_bodies():
    state = _state(population=0, bodies={
        "Body 1": {"PlanetClass": "Water world"},
        "Body 2": {"PlanetClass": "Metal-rich body"},
    })
    name, occupied_text, color, economy_text = _current_system_summary(state)
    assert occupied_text == "Unoccupied"
    assert economy_text == "Likely: Agriculture, Tourism, Extraction"


def test_unoccupied_system_no_scanned_bodies_yet():
    state = _state(population=0, bodies={})
    _, _, _, economy_text = _current_system_summary(state)
    assert economy_text == "not enough scanned yet"


def test_unknown_population_shows_placeholder():
    state = _state(population=None)
    name, occupied_text, color, economy_text = _current_system_summary(state)
    assert occupied_text == "—"
    assert economy_text == "—"


def test_ignores_non_dict_body_records():
    state = _state(population=0, bodies={"Body 1": "not a dict", "Body 2": {"PlanetClass": "Icy body"}})
    _, _, _, economy_text = _current_system_summary(state)
    assert economy_text == "Likely: Industrial"
