from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])  # keep a reference: a dropped QApplication crashes pytest

from edc.ui.panels.colonisation_panel import ColonisationPanel, _ColonisationDetailDialog  # noqa: E402


def _depot(provided, progress):
    return {"id": 9, "market_id": 1, "system_address": 2, "system_name": "HIP 109508",
            "station_name": "Equiano Territory", "progress": progress, "complete": 0,
            "resources": [{"name": "Water", "required": 2209, "provided": provided, "payment": 662},
                          {"name": "Steel", "required": 19436, "provided": 0, "payment": 5057}]}


def test_open_detail_window_follows_deliveries():
    # Live 2026-11-08: the open window kept showing pre-delivery numbers.
    repo = MagicMock()
    repo.get_system_coords_for_names.return_value = {}
    repo.get_colonisation_depots.return_value = [_depot(0, 0.0)]
    panel = ColonisationPanel(repo)
    dlg = _ColonisationDetailDialog(panel, _depot(0, 0.0))
    panel._depot_dialogs[9] = dlg
    dlg.show()
    assert dlg._table.rowCount() == 2

    repo.get_colonisation_depots.return_value = [_depot(1000, 0.008)]
    panel._refresh_depots(None)
    assert dlg._table.item(0, 2).text() == "1,000"
    assert dlg._table.item(0, 3).text() == "1,209"
    assert dlg._status_label.text().startswith("0.8% complete")

    # Fully delivered commodities drop off; only outstanding ones stay.
    repo.get_colonisation_depots.return_value = [_depot(2209, 0.017)]
    panel._refresh_depots(None)
    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "Steel"
    assert dlg._table.cellWidget(0, 6) is not None  # Find Source
    dlg.close()


def test_where_to_buy_groups_needs_by_station():
    from edc.core.commodity_categories import CommodityCategoryTable
    from pathlib import Path
    repo = MagicMock()
    repo.get_system_coords_for_names.return_value = {}
    repo.get_colonisation_depots.return_value = []
    panel = ColonisationPanel(repo, commodity_categories=CommodityCategoryTable(Path("settings")))
    depot = {"id": 9, "market_id": 1, "system_address": 2, "system_name": "", "station_name": "Site",
             "progress": 0.5, "complete": 0,
             "resources": [{"name": "Muon Imager", "required": 90, "provided": 0},
                           {"name": "Steel", "required": 2056, "provided": 1220},
                           {"name": "Robotics", "required": 118, "provided": 0}]}
    dlg = _ColonisationDetailDialog(panel, depot)   # no system name: no background lookup
    ts = "2026-11-14T10:00:00Z"
    dlg._on_sources({
        5: {"station_name": "Big Port", "system_name": "Sol", "pad_size": "L", "distance_ly": 12.0,
            "buys": {"mutomimager": (1, 500, ts), "steel": (1, 400, ts)}},
        6: {"station_name": "Steel Works", "system_name": "Lave", "pad_size": "L", "distance_ly": 30.0,
            "buys": {"steel": (1, 9000, ts)}},
    }, None)
    tree = dlg._sources_tree
    tops = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert [t.text(0) for t in tops] == ["Stop 1: Big Port — Sol", "Stop 2: Steel Works — Lave",
                                         "No seller within 150 ly"]
    assert [(tops[0].child(i).text(0).strip(), tops[0].child(i).text(1)) for i in range(2)] == [
        ("Muon Imager", "90"), ("Steel", "400")]
    assert tops[1].child(0).text(1) == "436"
    assert tops[2].child(0).text(0).strip() == "Robotics"
    assert dlg._trailblazer_label.text().endswith("none known yet.")
    # Double-click on a stop or on one of its commodities copies the stop's system name.
    tree.itemDoubleClicked.emit(tops[0].child(1), 0)
    assert QApplication.clipboard().text() == "Sol"


def test_materials_cell_opens_the_construction_window_and_remove_still_removes():
    repo = MagicMock()
    repo.get_system_coords_for_names.return_value = {}
    d = _depot(0, 0.0)
    d["system_name"] = ""          # no background lookup
    repo.get_colonisation_depots.return_value = [d]
    panel = ColonisationPanel(repo)
    panel._refresh_depots(None)
    assert panel._depot_table.item(0, 5).text().endswith("Materials")
    panel._on_depot_cell_clicked(0, 5)
    assert panel._depot_dialogs[9].isVisible()
    panel._depot_dialogs[9].close()
    panel._on_depot_cell_clicked(0, 6)
    repo.remove_colonisation_depot.assert_called_once_with(9)


def test_cargo_counts_against_what_to_buy_and_the_docked_station_is_listed_once():
    from types import SimpleNamespace
    from pathlib import Path
    from edc.core.commodity_categories import CommodityCategoryTable
    repo = MagicMock()
    repo.get_system_coords_for_names.return_value = {}
    repo.get_colonisation_depots.return_value = []
    panel = ColonisationPanel(repo, commodity_categories=CommodityCategoryTable(Path("settings")))
    panel._last_state = SimpleNamespace(
        ship=None, station_name="Big Port", current_market_id=5, current_market_system="Sol",
        cargo_inventory=[{"Name": "mutomimager", "Count": 90}, {"Name": "steel", "Count": 300}],
        current_market_items=[{"name": "Steel", "symbol": "steel", "buy_price": 4000, "stock": 400}])
    depot = {"id": 9, "market_id": 1, "system_address": 2, "system_name": "", "station_name": "Site",
             "progress": 0.5, "complete": 0,
             "resources": [{"name": "Muon Imager", "required": 90, "provided": 0},
                           {"name": "Steel", "required": 2056, "provided": 1220}]}
    dlg = _ColonisationDetailDialog(panel, depot)
    # Top table: Still Needed, In Cargo, To Buy.
    assert [dlg._table.item(0, c).text() for c in (3, 4, 5)] == ["90", "90", "0"]
    assert [dlg._table.item(1, c).text() for c in (3, 4, 5)] == ["836", "300", "536"]
    ts = "2026-11-14T10:00:00Z"
    dlg._on_sources({
        5: {"station_name": "Big Port", "system_name": "Sol", "pad_size": "L", "distance_ly": 12.0,
            "buys": {"steel": (1, 9000, ts)}},
        6: {"station_name": "Steel Works", "system_name": "Lave", "pad_size": "L", "distance_ly": 30.0,
            "buys": {"steel": (1, 9000, ts)}},
    }, None)
    tree = dlg._sources_tree
    tops = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    # The docked station appears once, with its live stock; another stop covers the rest.
    assert [t.text(0) for t in tops] == ["DOCKED HERE — Big Port: buy now", "Stop 1: Steel Works — Lave"]
    assert (tops[0].child(0).text(1), tops[0].child(0).text(2)) == ("400", "400")
    assert tops[1].child(0).text(1) == "136"
    # An unchanged refresh keeps the selected row.
    tree.setCurrentItem(tops[1])
    dlg.update_depot(depot)
    assert tree.currentItem() is tops[1]
    # Everything in the hold: nothing to buy.
    panel._last_state.cargo_inventory = [{"Name": "mutomimager", "Count": 90}, {"Name": "steel", "Count": 836}]
    dlg.update_depot(depot)
    assert tree.topLevelItemCount() == 0
    assert dlg._sources_label.text().endswith("is in the cargo hold")
