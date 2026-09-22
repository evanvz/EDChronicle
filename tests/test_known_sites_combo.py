"""ColonisationPanel's Known Sites combo -- selecting an entry fills the
manual-add text fields exactly, so a typo can't create an orphaned depot
row a real dock will never match. Also covers the combo's current-system
scoping and the station-name completer that narrows once a system with
more than one known site is typed. Pure logic exercised via a fake self."""
from types import SimpleNamespace

from edc.ui.panels.colonisation_panel import ColonisationPanel

_SITES = [
    {"system_name": "HIP 105879", "station_name": "Orbital Construction Site: Asling's Gift"},
    {"system_name": "HIP 105879", "station_name": "Planetary Construction Site: Second Port"},
    {"system_name": "Sol", "station_name": "Orbital Construction Site: Other System Site"},
]


class _FakeComboBox:
    """Records addItem() calls and answers itemData() from them --
    enough to assert what _rebuild_known_sites_combo_for_system() built
    without a real QComboBox."""
    def __init__(self):
        self.items = []  # list of (label, data)
        self.blocked = False
        self.current_index = 0

    def blockSignals(self, v):
        self.blocked = v

    def clear(self):
        self.items = []

    def addItem(self, label, data=None):
        self.items.append((label, data))

    def setCurrentIndex(self, i):
        self.current_index = i

    def itemData(self, index):
        return self.items[index][1]

    def itemText(self, index):
        return self.items[index][0]

    def count(self):
        return len(self.items)


class _FakeCompleter:
    def __init__(self):
        self.model_names = None

    def setModel(self, model):
        self.model_names = list(model.stringList()) if model is not None else None


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


def _fake_panel(system=None):
    return SimpleNamespace(
        _known_sites=_SITES,
        _known_sites_combo=_FakeComboBox(),
        _last_state=SimpleNamespace(system=system),
    )


def test_combo_scoped_to_current_system_only():
    fs = _fake_panel()
    ColonisationPanel._rebuild_known_sites_combo_for_system(fs, "HIP 105879")
    labels = [fs._known_sites_combo.itemText(i) for i in range(fs._known_sites_combo.count())]
    assert labels == [
        "Known sites in HIP 105879 (2)…",
        "Orbital Construction Site: Asling's Gift",
        "Planetary Construction Site: Second Port",
    ]


def test_combo_excludes_other_systems_sites():
    fs = _fake_panel()
    ColonisationPanel._rebuild_known_sites_combo_for_system(fs, "Sol")
    labels = [fs._known_sites_combo.itemText(i) for i in range(fs._known_sites_combo.count())]
    assert labels == ["Known sites in Sol (1)…", "Orbital Construction Site: Other System Site"]


def test_combo_empty_when_system_has_no_known_sites():
    fs = _fake_panel()
    ColonisationPanel._rebuild_known_sites_combo_for_system(fs, "Deciat")
    labels = [fs._known_sites_combo.itemText(i) for i in range(fs._known_sites_combo.count())]
    assert labels == ["Known sites in Deciat (0)…"]


def test_combo_placeholder_when_no_system_yet():
    fs = _fake_panel()
    ColonisationPanel._rebuild_known_sites_combo_for_system(fs, None)
    labels = [fs._known_sites_combo.itemText(i) for i in range(fs._known_sites_combo.count())]
    assert labels == ["Known sites — waiting for current system…"]


def test_station_completer_narrows_to_typed_systems_sites():
    fs = SimpleNamespace(_known_sites=_SITES, _depot_station_completer=_FakeCompleter())
    ColonisationPanel._on_depot_system_text_changed(fs, "HIP 105879")
    assert sorted(fs._depot_station_completer.model_names) == [
        "Orbital Construction Site: Asling's Gift",
        "Planetary Construction Site: Second Port",
    ]


def test_station_completer_case_insensitive():
    fs = SimpleNamespace(_known_sites=_SITES, _depot_station_completer=_FakeCompleter())
    ColonisationPanel._on_depot_system_text_changed(fs, "hip 105879")
    assert len(fs._depot_station_completer.model_names) == 2


def test_station_completer_empty_for_unknown_system():
    fs = SimpleNamespace(_known_sites=_SITES, _depot_station_completer=_FakeCompleter())
    ColonisationPanel._on_depot_system_text_changed(fs, "Deciat")
    assert fs._depot_station_completer.model_names == []


def test_station_completer_cleared_when_system_text_empty():
    fs = SimpleNamespace(_known_sites=_SITES, _depot_station_completer=_FakeCompleter())
    ColonisationPanel._on_depot_system_text_changed(fs, "")
    assert fs._depot_station_completer.model_names is None
