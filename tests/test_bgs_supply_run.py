"""BGS supply run: destination-first trade search for a squadron-faction
station in a system the pledged power controls."""
from datetime import datetime, timedelta, timezone

from edc.core.trade_routes import destination_pp_status, find_supply_for_destination
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_OLD = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _supply(name, x, buys):
    return {"station_name": name, "system_name": name + " Sys", "pad_size": "L",
            "x": x, "y": 0, "z": 0, "buys": buys, "sells": {}}


_DEST = {"station_name": "Lundmark Terminal", "system_name": "Ekono",
         "sells": {"gold": (10000, 500, _NOW), "tea": (1500, 0, _NOW), "silver": (5000, 50, _NOW)}}


def test_picks_most_profitable_supply_and_caps_by_demand():
    supply = {
        1: _supply("Near", 5, {"gold": (9000, 1000, _NOW)}),
        2: _supply("Far", 15, {"gold": (6000, 1000, _NOW), "silver": (4000, 1000, _NOW)}),
    }
    rows = find_supply_for_destination(_DEST, (0, 0, 0), supply, cargo_capacity=200)
    gold = next(r for r in rows if r["commodity"] == "gold")
    assert gold["buy_station_name"] == "Far" and gold["quantity"] == 200 and gold["total_profit"] == 800000
    silver = next(r for r in rows if r["commodity"] == "silver")
    assert silver["quantity"] == 50  # never sell past the destination's demand
    assert [r["commodity"] for r in rows] == ["gold", "silver"]


def test_zero_demand_and_loss_making_commodities_are_skipped():
    supply = {1: _supply("S", 5, {"tea": (100, 1000, _NOW), "gold": (12000, 1000, _NOW)})}
    assert find_supply_for_destination(_DEST, (0, 0, 0), supply, cargo_capacity=100) == []


def test_equal_profit_prefers_station_nearer_destination():
    supply = {
        1: _supply("Far", 18, {"gold": (9000, 1000, _NOW)}),
        2: _supply("Near", 3, {"gold": (9000, 1000, _NOW)}),
    }
    rows = find_supply_for_destination(_DEST, (0, 0, 0), supply, cargo_capacity=100)
    assert rows[0]["buy_station_name"] == "Near"
    assert rows[0]["dist_to_dest"] == 3


def test_destination_itself_is_not_a_supply_station():
    supply = {7: _supply("Lundmark Terminal", 0, {"gold": (1000, 1000, _NOW)})}
    assert find_supply_for_destination(_DEST, (0, 0, 0), supply, 100, dest_market_id=7) == []


def test_pp_merit_flag_needs_a_40_percent_margin():
    dest = {"sells": {"a": (1400, 100, _NOW), "b": (1390, 100, _NOW)}}
    supply = {1: _supply("S", 1, {"a": (1000, 100, _NOW), "b": (1000, 100, _NOW)})}
    flags = {r["commodity"]: r["pp_large_profit"] for r in find_supply_for_destination(dest, (0, 0, 0), supply, 10)}
    assert flags == {"a": True, "b": False}


def test_stale_rows_rank_below_fresh_ones():
    supply = {1: _supply("S", 1, {"gold": (1000, 1000, _OLD), "silver": (4900, 1000, _NOW)})}
    rows = find_supply_for_destination(_DEST, (0, 0, 0), supply, 100)
    assert [r["commodity"] for r in rows] == ["silver", "gold"]


# --- PowerPlay rule: destination system must be your power's ---

def test_pp_status_prefers_own_journal_over_edsm():
    journal = {"pp_controlling_power": "Aisling Duval", "pp_state": "Stronghold", "pp_data_timestamp": _NOW}
    edsm = {"power": "Zachary Hudson", "power_state": "Fortified"}
    assert destination_pp_status("Aisling Duval", journal, edsm) == ("ok", "Stronghold")


def test_pp_status_rejects_other_power_and_unoccupied():
    assert destination_pp_status("Aisling Duval", None, {"power": "Zachary Hudson", "power_state": "Fortified"}) \
        == ("no", "controlled by Zachary Hudson")
    assert destination_pp_status("Aisling Duval", None, {"power": "Aisling Duval", "power_state": "Unoccupied"}) \
        == ("no", "not controlled by any power")


def test_pp_status_unknown_system_is_unverified_not_rejected():
    assert destination_pp_status("Aisling Duval", None, None) == ("unverified", "PP unverified")
    assert destination_pp_status(None, None, None)[0] == "unverified"


# --- destination list from the DB ---

def test_faction_station_destinations(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.save_station_info(market_id=1, station_name="Lundmark Terminal", system_name="Ekono",
                           station_type="Orbis", pads_small=1, pads_medium=1, pads_large=1,
                           last_visited=_NOW, station_faction="Elite United Worlds")
    repo.save_station_info(market_id=2, station_name="Other Port", system_name="Ekono",
                           station_type="Orbis", pads_small=1, pads_medium=1, pads_large=1,
                           last_visited=_NOW, station_faction="Someone Else")
    repo.save_station_info(market_id=3, station_name="No Market Base", system_name="Ekono",
                           station_type="Outpost", pads_small=1, pads_medium=1, pads_large=0,
                           last_visited=_NOW, station_faction="Elite United Worlds")
    repo.save_market_snapshot_batch([
        (mid, "gold", name, "Orbis", "Ekono", 10000, None, 9000, 500, 3, 0, 0, _NOW)
        for mid, name in ((1, "Lundmark Terminal"), (2, "Other Port"))
    ])
    repo.save_system_powerplay_snapshot(
        system_address=99, system_name="Ekono", pp_state="Stronghold", control_progress=None,
        reinforcement=None, undermining=None, controlling_power="Aisling Duval",
        powers=["Aisling Duval"], data_timestamp=_NOW,
    )
    rows = repo.get_faction_station_destinations("elite united worlds")
    assert [r["station_name"] for r in rows] == ["Lundmark Terminal"]
    assert rows[0]["journal_pp"]["pp_controlling_power"] == "Aisling Duval"
