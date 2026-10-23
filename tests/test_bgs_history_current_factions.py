"""Arimavante, 2026-10-22: the BGS History window listed 7 factions EDSM keeps
at 0% after they left, showed EUW "At War, opponent unknown" because EDDN
brought only EUW's row, and called the pending war a "Conflict risk (0.0%)"."""
from types import SimpleNamespace

from edc.core.eddn_market import write_buffers
from edc.ui.panels.player_faction_panel import _format_forecast
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

ARI = 4756911035114
PENDING = [{"State": "War", "Trend": 0}]


def _repo(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_pending_war_named_for_both_sides(tmp_path):
    repo = _repo(tmp_path)
    for name, inf in (("Elite United Worlds", 0.1802), ("Cameron's Combat Services", 0.1802),
                      ("Aces Wild Aerospace Corporation", 0.4434)):
        f = {"Name": name, "Influence": inf, "PendingStates": PENDING if inf < 0.2 else None}
        repo.save_faction_snapshot(ARI, f, "2026-10-22", inf > 0.4, "2026-10-22T18:04:06Z", "journal")
    preds = {p["faction_name"]: p for p in repo.get_all_faction_predictions_for_system(ARI)}
    text, _ = _format_forecast(preds["Elite United Worlds"])
    assert text == "⚔ War pending vs Cameron's Combat Services (18.0%) — starts at the next tick"
    assert _format_forecast(preds["Cameron's Combat Services"])[0].startswith("⚔ War pending vs Elite United Worlds")
    assert _format_forecast(preds["Aces Wild Aerospace Corporation"])[0] != _format_forecast(preds["Elite United Worlds"])[0]
    repo.db.close()


def test_eddn_sighting_saves_every_faction_from_the_same_reading(tmp_path):
    repo = _repo(tmp_path)
    factions = [{"Name": "Aces Wild Aerospace Corporation", "Influence": 0.4434},
                {"Name": "Elite United Worlds", "Influence": 0.1802, "ActiveStates": [{"State": "War"}]},
                {"Name": "Cameron's Combat Services", "Influence": 0.1802, "ActiveStates": [{"State": "War"}]}]
    sighting = dict(factions[1], SystemFactions=factions)
    write_buffers(repo, [], [], [(ARI, ("Arimavante", sighting, False, "2026-10-22T18:35:01Z"))],
                  [], [], [], [], [], [])
    rows = {r["faction_name"]: r for r in repo.get_faction_history(ARI)}
    assert set(rows) == {f["Name"] for f in factions}
    assert rows["Aces Wild Aerospace Corporation"]["is_controlling"] == 1
    assert "SystemFactions" not in str(rows)
    war = {p["faction_name"]: p for p in repo.get_all_faction_predictions_for_system(ARI)}["Elite United Worlds"]["active_war"]
    assert war["faction_name"] == "Cameron's Combat Services"
    repo.db.close()


def test_history_window_shows_only_factions_present_now(tmp_path):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841 -- must outlive the dialog
    from edc.ui.panels.player_faction_panel import _FactionHistoryDialog
    repo = _repo(tmp_path)
    repo.save_faction_snapshot(ARI, {"Name": "Elite United Worlds", "Influence": 0.1802}, "2026-10-22", False,
                               "2026-10-22T18:04:06Z", "journal")
    repo.save_faction_snapshot(ARI, {"Name": "Wadj Wen as one", "Influence": 0.0}, "2026-10-22", False,
                               "2026-10-22T02:34:13Z", "edsm")
    dlg = _FactionHistoryDialog(SimpleNamespace(_repo=repo, _faction_name="Elite United Worlds"), ARI, "Arimavante")
    dlg.refresh()
    assert "Wadj Wen" not in dlg._forecast_label.text()
    assert [dlg._table.item(r, 1).text() for r in range(dlg._table.rowCount())] == ["Elite United Worlds"]
    repo.db.close()
