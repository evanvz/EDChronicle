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
                      "last": "2026-10-02T20:59:00Z"}
