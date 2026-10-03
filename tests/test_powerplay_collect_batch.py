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
                      "recent": {"hip 109203": {"station": "Sweet City", "last": "2026-10-02T20:53:19Z",
                                                "log": [("2026-10-02T20:53:19Z", 83)]},
                                 "hip 114709": {"station": "Verrier Vision", "last": "2026-10-02T20:59:00Z",
                                                "log": [("2026-10-02T20:59:00Z", 83)]}}}


def test_recent_per_system_and_minutes_since_last_collect_there():
    b = {}
    assert add_collect(b, "x", "Ban Vision", "Lagar", "2026-10-03T10:53:28Z", 250) is None
    add_collect(b, "x", "Axon Orbital", "Kauruku", "2026-10-03T11:45:51Z", 250)
    assert add_collect(b, "x", "Ban Vision", "Lagar", "2026-10-03T12:20:07Z", 250) == (12 * 60 + 20 - 53 - 10 * 60 + (7 - 28) / 60)
    assert set(b["x"]["recent"]) == {"lagar", "kauruku"}


def test_station_locks_after_two_loads_and_card_points_elsewhere():
    """Evan's evening run 2026-10-03: Ban Vision 240 t + 250 t, then greyed
    out 13 and 50 min later; Axon Orbital 260 t + 250 t, then greyed out."""
    from datetime import datetime, timezone
    from edc.core import bgs_tasks as bt
    b, k = {}, "aisling media materials"
    add_collect(b, k, "Axon Orbital", "Kauruku", "2026-10-03T18:04:22Z", 250)
    add_collect(b, k, "Axon Orbital", "Kauruku", "2026-10-03T18:04:28Z", 10)
    add_collect(b, k, "Ban Vision", "Lagar", "2026-10-03T18:21:33Z", 240)
    sup = [("Lagar", "Fortified", 15.8), ("Isiti", "Stronghold", 23.1),
           ("HIP 114709", "Stronghold", 28.1), ("Kauruku", "Stronghold", 29.5)]

    def info(h, m):
        return bt.commodity_info("Acquisition", "Aisling Duval", {}, now=datetime(2026, 10, 3, h, m, tzinfo=timezone.utc),
                                 supporting=sup, collect_batch=b)
    i = info(18, 25)   # one load taken -> a second one still likely
    assert i["station"] == {"station": "Ban Vision", "tonnes": 240, "locked": False}
    assert i["next_station"] is None
    add_collect(b, k, "Ban Vision", "Lagar", "2026-10-03T18:34:42Z", 250)
    i = info(18, 47)   # two loads -> locked, Kauruku had only one so far
    assert i["station"]["locked"] and i["next_station"] == ("Isiti", "", 23.1)
    add_collect(b, k, "Axon Orbital", "Kauruku", "2026-10-03T19:04:45Z", 250)
    i = info(19, 24)   # Ban Vision still locked 50 min on; Kauruku locked too
    assert i["station"]["station"] == "Axon Orbital" and i["station"]["locked"]
    assert [c[0] for c in i["open_supporting"]] == ["Isiti", "HIP 114709"]
    assert i["next_station"][0] == "Isiti"
    i = info(20, 10)   # >90 min after Ban Vision's last collect -> open again
    assert "Lagar" in [c[0] for c in i["open_supporting"]]
