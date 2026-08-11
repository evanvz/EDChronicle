"""Tests for FactionRefreshTracker's tick-tracking methods."""
import json

from edc.core.faction_refresh_tracker import FactionRefreshTracker


def test_last_refreshed_tick_is_none_before_anything_is_marked(tmp_path):
    tracker = FactionRefreshTracker(tmp_path / "faction_refresh.json")
    assert tracker.last_refreshed_tick() is None


def test_mark_and_read_back_refreshed_tick(tmp_path):
    tracker = FactionRefreshTracker(tmp_path / "faction_refresh.json")
    tracker.mark_refreshed_tick("2026-08-11T10:51:03+00:00")
    assert tracker.last_refreshed_tick() == "2026-08-11T10:51:03+00:00"


def test_marking_refreshed_tick_does_not_clobber_existing_keys(tmp_path):
    path = tmp_path / "faction_refresh.json"
    tracker = FactionRefreshTracker(path)
    tracker.mark_refreshed()
    tracker.mark_csv_imported()

    tracker.mark_refreshed_tick("2026-08-11T10:51:03+00:00")

    assert tracker.last_refresh() is not None
    assert tracker.last_csv_import() is not None
    assert tracker.last_refreshed_tick() == "2026-08-11T10:51:03+00:00"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"last_refresh", "last_csv_import", "last_refreshed_tick"}
