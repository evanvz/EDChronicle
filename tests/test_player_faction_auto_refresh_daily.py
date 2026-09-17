"""PlayerFactionPanel._maybe_auto_refresh_all() -- previously gated by a
permanent one-shot latch (self._auto_refresh_checked) that made this run
exactly once per app lifetime instead of once per calendar day, silently
starving a session left running for multiple days (confirmed live: never
re-checked past the first day, matching the market-prune retry-timer bug
fixed earlier this session). _start_refresh_all() already has its own
"already running" and "already fresh today" guards, so the latch was
pure redundant state -- removed. Uses the fake-self/SimpleNamespace
pattern already established for panel method tests, with a real
FactionRefreshTracker (tmp_path) since it's a simple file-backed class."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.core.faction_refresh_tracker import FactionRefreshTracker
from edc.ui.panels.player_faction_panel import PlayerFactionPanel


def _fake_self(tracker, start_refresh_all):
    return SimpleNamespace(
        _refresh_tracker=tracker,
        _faction_name="Test Faction",
        _start_refresh_all=start_refresh_all,
        _check_csv_staleness=lambda: None,
        _update_refresh_status_label=lambda last: None,
    )


def test_second_call_same_day_does_not_refresh_again(tmp_path):
    tracker = FactionRefreshTracker(tmp_path / "refresh.json")
    tracker.mark_refreshed()  # refreshed moments ago -- fresh today
    start_refresh_all = MagicMock(return_value=True)
    fake_self = _fake_self(tracker, start_refresh_all)

    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)
    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)

    start_refresh_all.assert_not_called()


def test_call_on_a_new_day_still_triggers_refresh_without_a_permanent_latch(tmp_path):
    # Regression for the one-shot-latch bug: last_refresh() is yesterday's
    # timestamp (the earlier attempt never actually completed -- e.g. no
    # systems to refresh, or the session closed mid-refresh), so a repeat
    # call representing "a new day, still running" must retry, not
    # silently no-op forever the way the removed self._auto_refresh_checked
    # flag made it do.
    tracker = FactionRefreshTracker(tmp_path / "refresh.json")
    data_path = tmp_path / "refresh.json"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    data_path.write_text(f'{{"last_refresh": "{yesterday}"}}', encoding="utf-8")

    start_refresh_all = MagicMock(return_value=True)
    fake_self = _fake_self(tracker, start_refresh_all)

    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)
    assert start_refresh_all.call_count == 1

    # Simulate a long-running session: many more ticks of the same day
    # (still no completed refresh recorded) must keep retrying, not stop
    # after the first attempt the way the old latch did.
    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)
    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)
    assert start_refresh_all.call_count == 3


def test_no_refresh_tracker_or_faction_name_is_a_noop():
    start_refresh_all = MagicMock(return_value=True)
    fake_self = _fake_self(None, start_refresh_all)
    PlayerFactionPanel._maybe_auto_refresh_all(fake_self)
    start_refresh_all.assert_not_called()

    fake_self2 = SimpleNamespace(
        _refresh_tracker=object(), _faction_name="", _start_refresh_all=start_refresh_all,
        _check_csv_staleness=lambda: None, _update_refresh_status_label=lambda last: None,
    )
    PlayerFactionPanel._maybe_auto_refresh_all(fake_self2)
    start_refresh_all.assert_not_called()
