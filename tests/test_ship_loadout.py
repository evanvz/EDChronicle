"""has_detailed_surface_scanner() (ship_loadout.py) -- mirrors
has_any_weapon()'s existing pattern for the "does this ship have a DSS
fitted" check, confirmed against real journal data: internal name
"int_detailedsurfacescanner_tiny" (no size/class variants, unlike
weapons, so no slot-pattern restriction)."""
from edc.core.ship_loadout import has_detailed_surface_scanner


def _module(slot, item):
    return {"Slot": slot, "Item": item}


def test_dss_fitted_returns_true():
    modules = [_module("Slot08_Size1", "int_detailedsurfacescanner_tiny")]
    assert has_detailed_surface_scanner(modules) is True


def test_no_dss_returns_false():
    modules = [
        _module("MediumHardpoint1", "hpt_pulselaser_fixed_medium"),
        _module("Slot06_Size3", "int_cargorack_size3_class1"),
    ]
    assert has_detailed_surface_scanner(modules) is False


def test_empty_modules_returns_false():
    assert has_detailed_surface_scanner([]) is False
    assert has_detailed_surface_scanner(None) is False


def test_malformed_module_entries_are_skipped_not_raised():
    modules = [None, "not a dict", {"Slot": "Slot01"}, _module("Slot08_Size1", "int_detailedsurfacescanner_tiny")]
    assert has_detailed_surface_scanner(modules) is True
