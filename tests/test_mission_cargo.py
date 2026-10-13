"""Mission Cargo: cargo missions tracked from MissionAccepted/CargoDepot, combined per
commodity + drop-off station, with what's still needed, what's in the hold and
what's left to buy; nearest and cheapest sources from the market search."""
from edc.core.mission_cargo import cargo_needs, commodity_aliases, pick_sources
from edc.core.mission_events import apply_mission_event


def _accept(mid, name="Mission_Collect_CivilLiberty", commodity="$AtmosphericExtractors_Name;",
            loc="Atmospheric Processors", count=32, station="Lundmark Terminal", expiry="2099-10-13T14:41:46Z"):
    return {"event": "MissionAccepted", "MissionID": mid, "Name": name, "Commodity": commodity,
            "Commodity_Localised": loc, "Count": count, "DestinationSystem": "Ekono",
            "DestinationStation": station, "Expiry": expiry, "Faction": "EUW"}


def test_accept_records_cargo_fields_and_cargodepot_tracks_delivery():
    active = {}
    apply_mission_event(active, _accept(1))
    rec = active[1]
    assert (rec["commodity"], rec["commodity_localised"], rec["count"]) == (
        "$AtmosphericExtractors_Name;", "Atmospheric Processors", 32)
    apply_mission_event(active, {"event": "CargoDepot", "MissionID": 1, "UpdateType": "Deliver",
                                 "ItemsDelivered": 20, "TotalItemsToDeliver": 32})
    assert active[1]["delivered"] == 20
    apply_mission_event(active, {"event": "CargoDepot", "MissionID": 99, "ItemsDelivered": 5})  # unknown mission
    assert 99 not in active
    apply_mission_event(active, {"event": "MissionCompleted", "MissionID": 1})
    assert active == {}


def test_missions_combine_per_commodity_and_station_with_hold_and_left_to_buy():
    active = {}
    for mid, count in ((1, 32), (2, 45), (3, 48)):
        apply_mission_event(active, _accept(mid, count=count, expiry=f"2099-10-1{mid + 2}T00:00:00Z"))
    apply_mission_event(active, _accept(4, commodity="$PowerGenerators_Name;", loc="Power Generators", count=63))
    apply_mission_event(active, {"event": "CargoDepot", "MissionID": 1, "ItemsDelivered": 10, "TotalItemsToDeliver": 32})
    apply_mission_event(active, {"event": "MissionAccepted", "MissionID": 5, "Name": "Mission_Massacre"})  # no cargo
    rows = cargo_needs(active, [{"Name": "atmosphericextractors", "Count": 40}])
    ap = next(r for r in rows if r["commodity"] == "Atmospheric Processors")
    assert (ap["missions"], ap["total"], ap["delivered"], ap["needed"], ap["held"], ap["to_buy"]) == (3, 125, 10, 115, 40, 75)
    assert ap["expiry"] == "2099-10-13T00:00:00Z" and ap["buyable"] and ap["station"] == "Lundmark Terminal"
    pg = next(r for r in rows if r["commodity"] == "Power Generators")
    assert (pg["needed"], pg["held"], pg["to_buy"]) == (63, 0, 63)
    assert len(rows) == 2


def test_delivery_and_salvage_missions_get_no_buy_suggestions():
    active = {}
    apply_mission_event(active, _accept(1, name="Mission_Delivery_Agriculture", commodity="$Grain_Name;", loc="Grain"))
    apply_mission_event(active, _accept(2, name="MISSION_Salvage_Refinery", commodity="$Wreckage_Name;", loc="Wreckage"))
    apply_mission_event(active, _accept(3, name="Mission_Mining", commodity="$Gold_Name;", loc="Gold"))
    buyable = {r["commodity"]: r["buyable"] for r in cargo_needs(active, [])}
    assert buyable == {"Grain": False, "Wreckage": False, "Gold": True}


def test_commodity_aliases_cover_every_stored_spelling():
    assert set(commodity_aliases("$AtmosphericExtractors_Name;", "Atmospheric Processors")) == {
        "atmosphericextractors", "AtmosphericExtractors", "$AtmosphericExtractors_Name;",
        "$atmosphericextractors_name;", "Atmospheric Processors"}


def test_pick_sources_nearest_and_cheapest_with_enough_stock_first():
    rows = [
        {"station_name": "Near Low Stock", "distance_ly": 2.0, "buy_price": 900, "stock": 10, "pad_size": "L"},
        {"station_name": "Near", "distance_ly": 5.0, "buy_price": 1200, "stock": 500, "pad_size": "L"},
        {"station_name": "Cheap", "distance_ly": 25.0, "buy_price": 800, "stock": 500, "pad_size": "L"},
        {"station_name": "Small Pad", "distance_ly": 1.0, "buy_price": 500, "stock": 500, "pad_size": "S"},
    ]
    got = pick_sources(rows, to_buy=100, required_pad="L")
    assert got["nearest"]["station_name"] == "Near" and got["cheapest"]["station_name"] == "Cheap"
    assert [r["station_name"] for r in got["all"]] == ["Near Low Stock", "Near", "Cheap"]  # pad-filtered, by distance
    assert pick_sources([], 10, None) == {"nearest": None, "cheapest": None, "all": []}


def test_buy_price_search_matches_aliases(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.save_system_coords_batch([("Near", 1.0, 0.0, 0.0, "2026-10-12T00:00:00Z")])
    now = "2099-01-01T00:00:00Z"
    repo.save_market_snapshot_batch([
        (1, "atmosphericextractors", "Low Port", "Coriolis", "Near", 0, 500, 0, 0, 0, 900, 3, now),
        (2, "AtmosphericExtractors", "Camel Port", "Coriolis", "Near", 0, 450, 0, 0, 0, 900, 3, now),
    ])
    plain = repo.search_market_buy_prices("atmosphericextractors", 0, 0, 0, 10)
    both = repo.search_market_buy_prices("atmosphericextractors", 0, 0, 0, 10,
                                         aliases=commodity_aliases("$AtmosphericExtractors_Name;", "Atmospheric Processors"))
    assert [r["station_name"] for r in plain] == ["Low Port"]
    assert sorted(r["station_name"] for r in both) == ["Camel Port", "Low Port"]


def test_panel_tab_shows_needs_nearest_cheapest_and_detail(tmp_path):
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication
    from edc.ui.panels.trade_route_panel import TradeRoutePanel
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    pads = SimpleNamespace(pad_size_for=lambda ship: "L" if ship == "type9" else None)
    panel = TradeRoutePanel(Repository(db), ship_pad_table=pads)
    active = {}
    for mid, count in ((1, 32), (2, 45), (3, 48)):
        apply_mission_event(active, _accept(mid, count=count))
    state = SimpleNamespace(system="Ekono", system_x=0.0, system_y=0.0, system_z=0.0, cargo_capacity=700,
                            pp_power=None, station_name=None, current_market_id=None, current_market_items=[],
                            current_market_station="", current_market_system="", route_destination_system="",
                            ship="type9", active_missions=active,
                            cargo_inventory=[{"Name": "atmosphericextractors", "Count": 25}])
    sources = [
        {"station_name": "Near Pricey", "system_name": "A", "distance_ly": 4.0, "buy_price": 1500, "stock": 900,
         "pad_size": "L", "last_updated": "2026-10-12T08:00:00Z"},
        {"station_name": "Far Cheap", "system_name": "B", "distance_ly": 22.0, "buy_price": 900, "stock": 900,
         "pad_size": "L", "last_updated": "2026-10-12T08:00:00Z"},
        {"station_name": "Outpost", "system_name": "C", "distance_ly": 1.0, "buy_price": 500, "stock": 900,
         "pad_size": "M", "last_updated": "2026-10-12T08:00:00Z"},
    ]
    seen = []

    def fake_search(self, name, x, y, z, radius, exclude_market_id=None, aliases=None):
        seen.append((name, tuple(aliases or ())))
        return [dict(s) for s in sources]

    with patch.object(Repository, "search_market_buy_prices", fake_search):
        panel.refresh(state)
        deadline = time.time() + 10
        while panel._cargo_table.rowCount() == 0 or not panel._cargo_sources:
            app.processEvents(); time.sleep(0.02)
            assert time.time() < deadline
        panel._cargo_thread.wait(5000); app.processEvents()
    t = panel._cargo_table
    cells = [t.item(0, c).text() for c in range(t.columnCount())]
    assert cells[:6] == ["Atmospheric Processors", "Lundmark Terminal (Ekono)", "3", "125", "25", "100"]
    assert cells[7].startswith("Near Pricey · A — 4.0 ly, 1,500 cr")        # outpost excluded: L pad ship
    assert cells[8].startswith("Far Cheap · B — 22.0 ly, 900 cr")
    assert seen and "AtmosphericExtractors" in seen[0][1]                     # searched every spelling
    t.selectRow(0); app.processEvents()
    assert [panel._cargo_detail.item(r, 0).text() for r in range(panel._cargo_detail.rowCount())] == [
        "Near Pricey", "Far Cheap"]
    panel._cargo_pad_combo.setCurrentIndex(1)  # Any pad: the outpost comes back, nearest
    app.processEvents()
    assert t.item(0, 7).text().startswith("Outpost · C")


def test_on_foot_and_expired_missions_are_left_out():
    """Real journal history 2026-10-12: Mission_OnFoot_* items (Suit Schematic...) from
    2024/2025 never got a MissionFailed, so they still sat in active_missions."""
    from datetime import datetime, timezone
    active = {}
    apply_mission_event(active, _accept(1, name="Mission_OnFoot_Salvage_MB", commodity="$SuitSchematic_Name;",
                                        loc="Suit Schematic", count=1, expiry="2099-01-01T00:00:00Z"))
    apply_mission_event(active, _accept(2, name="Mission_Collect", commodity="$Gold_Name;", loc="Gold",
                                        expiry="2024-04-10T21:00:00Z"))
    apply_mission_event(active, _accept(3, name="Mission_Collect", commodity="$DomesticAppliances_Name;",
                                        loc="Domestic Appliances", count=448, expiry="2026-10-13T15:49:26Z"))
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    assert [g["commodity"] for g in cargo_needs(active, [], now=now)] == ["Domestic Appliances"]


def test_fleet_carriers_with_blank_station_type_are_excluded(tmp_path):
    """Real data 2026-10-12: 2,637 carrier markets have station_type '' (not NULL, not
    'FleetCarrier') and slipped past the carrier filter; their callsign names give them away."""
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.save_system_coords_batch([("Near", 1.0, 0.0, 0.0, "2026-10-12T00:00:00Z")])
    now = "2099-01-01T00:00:00Z"
    repo.save_market_snapshot_batch([
        (1, "gold", "Real Port", "Coriolis", "Near", 0, 500, 0, 0, 0, 900, 3, now),
        (2, "gold", "GFG-B6N", "", "Near", 0, 400, 0, 0, 0, 900, 3, now),
    ])
    assert [r["station_name"] for r in repo.search_market_buy_prices("gold", 0, 0, 0, 10)] == ["Real Port"]
    assert [s["station_name"] for s in repo.get_market_snapshot_in_radius(0, 0, 0, 10).values()] == ["Real Port"]
    assert [s["station_name"] for s in repo.get_market_snapshot_for_systems(["Near"]).values()] == ["Real Port"]


def test_startup_scan_drops_missions_that_expired_offline(tmp_path):
    """A mission that runs out while the game is closed never gets a MissionFailed;
    the startup history scan must not bring it back as active (Player Faction card,
    Combat panel and Mission Cargo all read active_missions)."""
    import json
    from edc.core.mission_scanner import scan_active_missions
    lines = [_accept(1, name="Mission_OnFoot_Salvage_MB", expiry="2024-04-10T21:00:00Z"),
             _accept(2, expiry="2099-01-01T00:00:00Z")]
    (tmp_path / "Journal.2026-10-12T000000.01.log").write_text(
        "\n".join(json.dumps({**e, "timestamp": "2024-04-01T00:00:00Z"}) for e in lines), encoding="utf-8")
    assert list(scan_active_missions(tmp_path)) == [2]
