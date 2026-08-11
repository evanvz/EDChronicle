"""Tests for _should_start_tick_refresh() -- the pure decision logic
behind PlayerFactionPanel.maybe_refresh_for_tick(). Deliberately has no
Qt/QApplication dependency so it can be tested directly."""
from edc.ui.panels.player_faction_panel import _should_start_tick_refresh


def test_starts_refresh_on_genuinely_new_tick():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick="2026-08-10T09:12:44+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is True


def test_does_not_start_when_tick_is_none():
    assert _should_start_tick_refresh(
        tick_iso=None,
        last_refreshed_tick="2026-08-10T09:12:44+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_tick_already_handled():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick="2026-08-11T10:51:03+00:00",
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_no_faction_known():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name=None,
        refresh_already_running=False,
    ) is False


def test_does_not_start_when_refresh_already_running():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name="Some Faction",
        refresh_already_running=True,
    ) is False


def test_starts_refresh_on_first_ever_tick_seen():
    assert _should_start_tick_refresh(
        tick_iso="2026-08-11T10:51:03+00:00",
        last_refreshed_tick=None,
        faction_name="Some Faction",
        refresh_already_running=False,
    ) is True
