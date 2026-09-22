"""ColonisationPanel's Known Sites combo -- selecting an entry fills the
manual-add text fields exactly, so a typo can't create an orphaned depot
row a real dock will never match. Pure logic exercised via a fake self."""
from types import SimpleNamespace

from edc.ui.panels.colonisation_panel import ColonisationPanel


def _fake_combo(item_data):
    return SimpleNamespace(itemData=lambda index: item_data.get(index))


def test_selecting_a_site_fills_both_fields():
    system_text = {"value": ""}
    station_text = {"value": ""}
    fake_self = SimpleNamespace(
        _known_sites_combo=_fake_combo({1: {"system_name": "HIP 105879", "station_name": "Orbital Construction Site: Asling's Gift"}}),
        _depot_system_edit=SimpleNamespace(setText=lambda v: system_text.__setitem__("value", v)),
        _depot_station_edit=SimpleNamespace(setText=lambda v: station_text.__setitem__("value", v)),
    )
    ColonisationPanel._on_known_site_selected(fake_self, 1)
    assert system_text["value"] == "HIP 105879"
    assert station_text["value"] == "Orbital Construction Site: Asling's Gift"


def test_selecting_the_placeholder_row_does_nothing():
    calls = []
    fake_self = SimpleNamespace(
        _known_sites_combo=_fake_combo({0: None}),
        _depot_system_edit=SimpleNamespace(setText=lambda v: calls.append(v)),
        _depot_station_edit=SimpleNamespace(setText=lambda v: calls.append(v)),
    )
    ColonisationPanel._on_known_site_selected(fake_self, 0)
    assert calls == []
