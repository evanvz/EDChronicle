"""Station owners from Spansh's system dump fill the gaps in our EDDN-built
station list -- owned Odyssey settlements are mostly missing there (HIP 114880,
2026-10-18: 9 known vs 63 on Spansh; Empire Party owned 13, none known)."""
from unittest.mock import MagicMock, patch

from edc.core.bgs_tasks import DEFAULT_LIMITS, build_task_view
from edc.core.spansh_client import fetch_system_stations
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

DUMP = {"system": {"name": "HIP 114880", "stations": [
    {"id": 1, "name": "Mitchell Terminal", "type": "Orbis Starport", "controllingFaction": "Elite United Worlds",
     "landingPads": {"large": 6, "medium": 18, "small": 17}, "services": ["Market"], "updateTime": "2026-10-12T00:00:00Z"},
    {"id": 2, "name": "H2F-3TT", "type": "Drake-Class Carrier", "controllingFaction": "FleetCarrier"}],
    "bodies": [{"name": "HIP 114880 A 1", "stations": [
        {"id": 3854648320, "name": "Martin Hydroponics Range", "type": "Settlement",
         "controllingFaction": "HIP 114880 Empire Party", "landingPads": {"large": 1, "medium": 0, "small": 1},
         "services": ["Dock", "Market", "Black Market"], "updateTime": "2024-05-29T20:34:19Z"}]}]}}


def _stations():
    resp = MagicMock()
    resp.json.return_value = DUMP
    with patch("edc.core.spansh_client.requests.get", return_value=resp):
        return fetch_system_stations(1487962868083)


def test_dump_parsed_with_settlements_and_without_carriers():
    rows = {r["station_name"]: r for r in _stations()}
    assert set(rows) == {"Mitchell Terminal", "Martin Hydroponics Range"}
    s = rows["Martin Hydroponics Range"]
    assert (s["station_faction"], s["system_name"], s["pads_large"]) == ("HIP 114880 Empire Party", "HIP 114880", 1)
    assert s["station_services"] == '["commodities", "blackmarket"]'


def test_gaps_filled_but_known_stations_kept(tmp_path):
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    db.conn.execute("INSERT INTO net.station_info (market_id, station_name, system_name, station_faction, last_visited) "
                    "VALUES (1, 'Mitchell Terminal', 'HIP 114880', 'Elite United Worlds', '2026-10-18T10:33:29Z')")
    assert repo.save_spansh_stations(_stations()) == 1                   # only the settlement is new
    assert repo.get_station_info(1)["last_visited"] == "2026-10-18T10:33:29Z"
    owned = repo.find_faction_stations_in_system("HIP 114880", "HIP 114880 Empire Party")
    task = {"id": 1, "system_address": 1487962868083, "system_name": "HIP 114880", "task_type": "hinder",
            "faction_name": "HIP 114880 Empire Party", "opponent_name": None, "note": None, "sort_order": 0,
            "created_at": "", "pp_mode": None}
    view = build_task_view(task, {}, None, [], None, dict(DEFAULT_LIMITS), faction_stations=owned)
    assert "Their stations here: Martin Hydroponics Range (L pad · market · black market · data 2024-05)" in view["lines"]
    db.close()
