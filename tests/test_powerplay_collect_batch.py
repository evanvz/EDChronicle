"""add_collect() and the Acquisition card's "next load" chip. The PowerPlay
allocation is one pool per commander, shared by every station (seen in
game 2026-10-03: Isiti stayed greyed out until ~25 min after a Ban Vision
collect). Data from Evan's journal 2026-10-03."""
from datetime import datetime, timezone

from edc.core import bgs_tasks as bt
from edc.core.powerplay_pledge_scanner import add_collect

K = "aisling media materials"


def test_same_station_within_window_adds_up_then_resets():
    b = {}
    add_collect(b, K, "Ban Vision", "Lagar", "2026-10-03T10:10:40Z", 176)
    add_collect(b, K, "Ban Vision", "Lagar", "2026-10-03T10:15:31Z", 84)
    assert b[K]["tonnes"] == 260
    add_collect(b, K, "Ban Vision", "Lagar", "2026-10-03T10:53:28Z", 250)
    assert b[K]["tonnes"] == 250


def test_other_station_starts_new_batch():
    b = {}
    add_collect(b, "x", "Sweet City", "HIP 109203", "2026-10-02T20:53:19Z", 83)
    add_collect(b, "x", "Verrier Vision", "HIP 114709", "2026-10-02T20:59:00Z", 83)
    assert b["x"] == {"station": "Verrier Vision", "system": "HIP 114709", "tonnes": 83,
                      "last": "2026-10-02T20:59:00Z"}


def test_returns_minutes_since_previous_collect_anywhere():
    b = {}
    assert add_collect(b, K, "Ban Vision", "Lagar", "2026-10-03T20:33:04Z", 250) is None
    assert round(add_collect(b, K, "Altuna Port", "Isiti", "2026-10-03T20:58:17Z", 250)) == 25


def _chip(view, start):
    return next(c for c in view["chips"] if c["text"].startswith(start))


def test_next_load_chip_is_shared_across_stations():
    sup = [("Lagar", "Fortified", 15.8), ("Isiti", "Stronghold", 23.1)]
    b = {}
    add_collect(b, K, "Altuna Port", "Isiti", "2026-10-03T20:58:17Z", 250)
    last = {K: "2026-10-03T20:58:17Z"}

    def view(h, m):
        info = bt.commodity_info("Acquisition", "Aisling Duval", {}, last,
                                 now=datetime(2026, 10, 3, h, m, tzinfo=timezone.utc),
                                 supporting=sup, collect_system={K: "Isiti"}, collect_batch=b)
        v = {"warnings": []}
        bt._add_powerplay_structure(v, "Acquisition", "", "Aisling Duval", None, None, {}, "", "", None, 0, info)
        return v
    ready_at = datetime(2026, 10, 3, 21, 28, 17, tzinfo=timezone.utc).astimezone().strftime("%H:%M")
    chip = _chip(view(21, 11), "Next load")   # Isiti greyed out at 21:11
    assert chip["text"] == f"Next load ≈{ready_at} · any supporting station"
    assert "Last load: 250 t at Altuna Port (Isiti)" in chip["tooltip"]
    assert _chip(view(21, 30), "Load ready")["text"] == "Load ready · any supporting station"
    assert _chip(view(21, 30), "Collect at")["text"] == "Collect at Lagar · 15.8 ly"


def test_any_commodity_collect_starts_the_shared_timer():
    """All three commodities grey out together (seen in game 2026-10-03)."""
    b = {}
    add_collect(b, K, "Altuna Port", "Isiti", "2026-10-03T20:58:17Z", 250)
    add_collect(b, "aisling sealed contracts", "Ban Vision", "Lagar", "2026-10-03T21:20:00Z", 250)
    last = {K: "2026-10-03T20:58:17Z", "aisling sealed contracts": "2026-10-03T21:20:00Z"}
    info = bt.commodity_info("Acquisition", "Aisling Duval", {}, last,
                             now=datetime(2026, 10, 3, 21, 35, tzinfo=timezone.utc), collect_batch=b)
    assert info["next_allocation"] != "now"
    assert info["batch"]["station"] == "Ban Vision"
