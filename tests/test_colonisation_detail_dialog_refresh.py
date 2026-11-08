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
    assert dlg._table.cellWidget(0, 4) is not None  # Find Source
    dlg.close()
