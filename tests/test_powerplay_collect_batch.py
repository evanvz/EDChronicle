"""add_collect(): tonnes taken per commodity in the current 30-min
allocation window, per station. Data from Evan's journal 2026-10-03."""
from edc.core.powerplay_pledge_scanner import add_collect


def test_same_station_within_window_adds_up_then_resets():
    b = {}
    add_collect(b, "aisling media materials", "Ban Vision", "Lagar", "2026-10-03T10:10:40Z", 176)
    add_collect(b, "aisling media materials", "Ban Vision", "Lagar", "2026-10-03T10:15:31Z", 84)
    assert b["aisling media materials"]["tonnes"] == 260
    add_collect(b, "aisling media materials", "Ban Vision", "Lagar", "2026-10-03T10:53:28Z", 250)
    assert b["aisling media materials"]["tonnes"] == 250


def test_other_station_starts_new_window():
    b = {}
    add_collect(b, "x", "Sweet City", "HIP 109203", "2026-10-02T20:53:19Z", 83)
    add_collect(b, "x", "Verrier Vision", "HIP 114709", "2026-10-02T20:59:00Z", 83)
    assert b["x"] == {"station": "Verrier Vision", "system": "HIP 114709", "tonnes": 83,
                      "last": "2026-10-02T20:59:00Z",
                      "recent": {"hip 109203": {"station": "Sweet City", "last": "2026-10-02T20:53:19Z"},
                                 "hip 114709": {"station": "Verrier Vision", "last": "2026-10-02T20:59:00Z"}}}


def test_recent_per_system_and_minutes_since_last_collect_there():
    b = {}
    assert add_collect(b, "x", "Ban Vision", "Lagar", "2026-10-03T10:53:28Z", 250) is None
    add_collect(b, "x", "Axon Orbital", "Kauruku", "2026-10-03T11:45:51Z", 250)
    assert add_collect(b, "x", "Ban Vision", "Lagar", "2026-10-03T12:20:07Z", 250) == (12 * 60 + 20 - 53 - 10 * 60 + (7 - 28) / 60)
    assert set(b["x"]["recent"]) == {"lagar", "kauruku"}


def test_card_points_to_next_supporting_station_while_this_one_refills():
    from datetime import datetime, timezone
    from edc.core import bgs_tasks as bt
    b = {}
    add_collect(b, "aisling media materials", "Axon Orbital", "Kauruku", "2026-10-03T11:45:51Z", 250)
    add_collect(b, "aisling media materials", "Ban Vision", "Lagar", "2026-10-03T12:20:07Z", 250)
    sup = [("Lagar", "Stronghold", 24.0), ("Kauruku", "Stronghold", 26.0), ("HIP 114709", "Stronghold", 28.1)]
    info = bt.commodity_info("Acquisition", "Aisling Duval", {}, now=datetime(2026, 10, 3, 12, 27, tzinfo=timezone.utc),
                             supporting=sup, collect_batch=b)
    assert info["refill_min"] == 6
    assert info["next_station"] == ("Kauruku", "Axon Orbital", 26.0)
    # Kauruku used 10 min ago too -> skip to HIP 114709
    add_collect(b, "aisling media materials", "Axon Orbital", "Kauruku", "2026-10-03T12:25:00Z", 250)
    info = bt.commodity_info("Acquisition", "Aisling Duval", {}, now=datetime(2026, 10, 3, 12, 35, tzinfo=timezone.utc),
                             supporting=sup, collect_batch=b)
    assert info["next_station"] == ("HIP 114709", "", 28.1)
