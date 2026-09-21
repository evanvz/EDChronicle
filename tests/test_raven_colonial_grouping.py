"""_RavenColonialDialog's category grouping and Assigned-commander
inversion -- pure logic exercised via a fake self (SimpleNamespace), same
pattern as test_raven_colonial_pad_filter.py."""
from types import SimpleNamespace

from edc.ui.panels.colonisation_panel import _RavenColonialDialog


class _FakeCategoryTable:
    _DATA = {
        "aluminium": ("Metals", "Aluminium"),
        "steel": ("Metals", "Steel"),
        "water": ("Chemicals", "Water"),
        "cmmcomposite": ("Industrial Materials", "CMM Composite"),
    }

    def category_for(self, symbol):
        rec = self._DATA.get(symbol)
        return rec[0] if rec else None

    def display_name_for(self, symbol):
        rec = self._DATA.get(symbol)
        return rec[1] if rec else None


def _fake_dialog(project, commodity_categories=None):
    panel = SimpleNamespace(_commodity_categories=commodity_categories or _FakeCategoryTable())
    return SimpleNamespace(_panel=panel, _project=project)


def test_assigned_commanders_inverts_commander_map():
    project = {"commanders": {"Alice": ["aluminium", "steel"], "Bob": ["aluminium"], "Carol": []}}
    fs = _fake_dialog(project)
    assigned = _RavenColonialDialog._assigned_commanders(fs)
    assert assigned == {"aluminium": ["Alice", "Bob"], "steel": ["Alice"]}


def test_assigned_commanders_empty_when_no_project():
    fs = _fake_dialog(None)
    assert _RavenColonialDialog._assigned_commanders(fs) == {}


def test_grouped_rows_groups_by_category_alphabetically():
    fs = _fake_dialog({})
    remaining = {"steel": 100, "aluminium": 50, "water": 10, "cmmcomposite": 5}
    grouped = _RavenColonialDialog._grouped_rows(fs, remaining)
    categories = [cat for cat, _ in grouped]
    assert categories == ["Chemicals", "Industrial Materials", "Metals"]


def test_grouped_rows_sorts_entries_alphabetically_within_category():
    fs = _fake_dialog({})
    remaining = {"steel": 100, "aluminium": 50}
    grouped = _RavenColonialDialog._grouped_rows(fs, remaining)
    metals = dict(grouped)["Metals"]
    assert [e[1] for e in metals] == ["Aluminium", "Steel"]


def test_grouped_rows_falls_back_to_other_for_unknown_commodity():
    fs = _fake_dialog({})
    remaining = {"unobtainium": 1}
    grouped = _RavenColonialDialog._grouped_rows(fs, remaining)
    assert grouped == [("Other", [("unobtainium", "Unobtainium", 1)])]


def test_grouped_rows_handles_no_category_table():
    fs = _fake_dialog({}, commodity_categories=None)
    fs._panel._commodity_categories = None
    remaining = {"aluminium": 1}
    grouped = _RavenColonialDialog._grouped_rows(fs, remaining)
    assert grouped[0][0] == "Other"
