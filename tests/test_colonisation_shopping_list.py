"""_aggregate_shopping_list() -- sums still-needed commodity amounts
across every incomplete tracked colonisation depot. Pure function, no Qt
needed."""
from edc.ui.panels.colonisation_panel import _aggregate_shopping_list


def _depot(resources, complete=False):
    return {"resources": resources, "complete": complete}


def test_sums_same_commodity_across_two_sites():
    depots = [
        _depot([{"name": "Steel", "required": 100, "provided": 40}]),
        _depot([{"name": "Steel", "required": 50, "provided": 10}]),
    ]
    result = _aggregate_shopping_list(depots)
    assert result == [("Steel", 100, 2)]  # (100-40) + (50-10) = 60+40 = 100, 2 sites


def test_fully_provided_commodity_excluded():
    depots = [_depot([{"name": "Steel", "required": 100, "provided": 100}])]
    assert _aggregate_shopping_list(depots) == []


def test_overprovided_commodity_not_negative():
    depots = [_depot([{"name": "Steel", "required": 100, "provided": 150}])]
    assert _aggregate_shopping_list(depots) == []


def test_complete_site_excluded_entirely():
    depots = [_depot([{"name": "Steel", "required": 100, "provided": 0}], complete=True)]
    assert _aggregate_shopping_list(depots) == []


def test_sorted_by_amount_descending():
    depots = [_depot([
        {"name": "Copper", "required": 10, "provided": 0},
        {"name": "Titanium", "required": 500, "provided": 0},
        {"name": "Iron", "required": 100, "provided": 0},
    ])]
    result = _aggregate_shopping_list(depots)
    assert [r[0] for r in result] == ["Titanium", "Iron", "Copper"]


def test_missing_name_skipped():
    depots = [_depot([{"required": 100, "provided": 0}])]
    assert _aggregate_shopping_list(depots) == []


def test_missing_required_or_provided_treated_as_zero():
    depots = [_depot([{"name": "Steel", "provided": 10}])]
    result = _aggregate_shopping_list(depots)
    assert result == []  # required=0 (missing), provided=10 -> remaining = max(0, -10) = 0


def test_non_dict_resource_entries_skipped():
    depots = [_depot(["not a dict", {"name": "Steel", "required": 10, "provided": 0}])]
    result = _aggregate_shopping_list(depots)
    assert result == [("Steel", 10, 1)]


def test_no_depots_returns_empty():
    assert _aggregate_shopping_list([]) == []


def test_depot_with_no_resources_key():
    assert _aggregate_shopping_list([{"complete": False}]) == []
