"""The faction refresh reads EDDataHub's /api/system-factions (one request per 100
systems) and asks EDSM only for the systems the hub doesn't have."""
from unittest import mock

from edc.core import eddatahub_client
from edc.ui.panels.player_faction_panel import _FactionRefreshWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_WAR = {"WarType": "civilwar", "Status": "active",
        "Faction1": {"Name": "Us", "WonDays": 2}, "Faction2": {"Name": "Them", "WonDays": 1}}
_HUB_ROW = {"system": 1, "name": "Alpha", "controlling": "Us", "updated": "2026-10-24T18:00:00+00:00",
            "factions": [{"Name": "Us", "Influence": 0.4, "FactionState": "Civil War", "Happiness": "Happy",
                          "MyReputation": 100, "ActiveStates": [{"State": "Civil War"}, {"State": "Civil Unrest"}],
                          "updated": "2026-10-24T18:00:00+00:00"},
                         {"Name": "Them", "Influence": 0.4, "FactionState": "Terrorist Attack",
                          "updated": "2026-10-24T18:00:00+00:00"}],
            "conflicts": [_WAR]}


def _resp(rows):
    r = mock.Mock(status_code=200)
    r.raise_for_status.return_value = None
    r.json.return_value = rows
    return r


def test_hub_rows_come_back_in_edsm_shape_with_journal_state_names():
    with mock.patch.object(eddatahub_client.requests, "get", return_value=_resp([_HUB_ROW, {**_HUB_ROW, "system": 9}])):
        got = eddatahub_client.fetch_system_factions("http://hub:8080", [1, 2])
    assert list(got) == [1]                                  # 9 wasn't asked for
    us, them = got[1]["factions"]
    assert us["FactionState"] == "CivilWar" and us["ActiveStates"] == [{"State": "CivilWar"}, {"State": "CivilUnrest"}]
    assert us["is_controlling"] and not them["is_controlling"] and them["FactionState"] == "Terrorism"
    assert "MyReputation" not in us and us["LastUpdate"] == "2026-10-24T18:00:00Z"
    assert got[1]["conflicts"] == [_WAR]
    with mock.patch.object(eddatahub_client.requests, "get", side_effect=OSError("down")):
        assert eddatahub_client.fetch_system_factions("http://hub:8080", [1]) is None


def test_refresh_uses_hub_and_edsm_only_for_the_rest(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    for addr, name in ((1, "Alpha"), (2, "Bravo")):
        repo.save_system_name_if_missing(addr, name)
        repo.save_faction_snapshot(addr, {"Name": "Us", "Influence": 0.3}, "2026-10-20", False,
                                   "2026-10-20T00:00:00Z", "edsm")
    db.close()
    edsm = mock.Mock(return_value=({"system_address": 2, "system_name": "Bravo",
                                    "factions": [{"Name": "Us", "Influence": 0.5, "is_controlling": True}]}, None))
    with mock.patch.object(eddatahub_client.requests, "get", return_value=_resp([_HUB_ROW])), \
         mock.patch("edc.ui.panels.player_faction_panel.fetch_system_factions", edsm), \
         mock.patch("edc.ui.panels.player_faction_panel.fetch_system_coords", return_value=None), \
         mock.patch("edc.ui.panels.player_faction_panel.time.sleep"):
        _FactionRefreshWorker(path, ["alpha", "bravo"], "Us", "http://hub:8080").run()
    assert [c.args[0] for c in edsm.call_args_list] == ["bravo"]
    db = Database(path)
    rows = db.conn.execute("SELECT system_address, influence, source FROM faction_snapshots "
                           "WHERE faction_name = 'Us' AND snapshot_date != '2026-10-20' ORDER BY 1").fetchall()
    assert [tuple(r) for r in rows] == [(1, 0.4, "hub"), (2, 0.5, "edsm")]
    status = db.conn.execute("SELECT conflicts, source FROM net.system_bgs_status WHERE system_address = 1").fetchone()
    assert '"won_days1": 2' in status[0] and status[1] == "hub"
    db.close()
