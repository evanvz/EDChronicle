"""Megaship datalinks pay merits once per megaship per fortnight (Doncaster's
Powerplay Reference Card), so a visit counts as 'seen' for 14 days only."""
import json

from edc.core.megaship_scanner import scan_visited_megaships
from edc.core.megaship_tracker import MegashipTracker


def test_seen_for_fourteen_days_then_rescannable(tmp_path):
    t = MegashipTracker(tmp_path / "m.json")
    k = MegashipTracker.key(42, "CAO-396 Beckett-class Researcher")
    t.mark_seen(k, "2026-10-01T12:00:00Z")
    assert t.has_seen(k, now="2026-10-15T11:59:59Z")
    assert not t.has_seen(k, now="2026-10-15T12:00:00Z")
    t.merge_seen({k: "2026-09-20T00:00:00Z"})                 # older visit doesn't move it back
    assert MegashipTracker(tmp_path / "m.json").has_seen(k, now="2026-10-10T00:00:00Z")


def test_old_seen_list_without_times_is_dropped(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps({"seen": ["42|X"]}))
    assert not MegashipTracker(tmp_path / "m.json").has_seen("42|X")


def test_journal_scan_keeps_latest_visit_time(tmp_path):
    events = [
        {"timestamp": "2026-10-01T10:00:00Z", "event": "FSDJump", "SystemAddress": 42},
        {"timestamp": "2026-10-01T10:01:00Z", "event": "FSSSignalDiscovered", "SignalType": "Megaship", "SignalName": "X"},
        {"timestamp": "2026-10-01T10:05:00Z", "event": "SupercruiseDestinationDrop", "Type": "X"},
        {"timestamp": "2026-10-09T10:05:00Z", "event": "SupercruiseDestinationDrop", "Type": "X"},
    ]
    (tmp_path / "Journal.2026-10-01T100000.01.log").write_text("\n".join(json.dumps(e) for e in events))
    assert scan_visited_megaships(tmp_path) == {"42|X": "2026-10-09T10:05:00Z"}
