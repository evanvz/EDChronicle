"""Frontier patch notes / dev logs in the news ticker, and the game-version notice."""
from datetime import datetime, timezone
from unittest import mock

from edc.core import galnet_news
from edc.core.game_version import note_game_version

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _resp(items):
    r = mock.Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"data": [{"attributes": a} for a in items]}
    return r


def test_recent_update_notes_and_dev_logs_newest_first():
    updates = [{"title": "Elite Dangerous: Anaconda MK II Update", "published_at": "2026-10-20T11:00:00+00:00",
                "field_version": {"value": "4.4.2.0"}},
               {"title": "Elite Dangerous - 4.4.1.1 Update Notes", "published_at": "2026-09-03T11:00:00+00:00",
                "field_version": "4.4.1.1"},                                      # older than 14 days
               {"title": "Elite Dangerous: Next", "published_at": "2026-10-30T11:00:00+00:00"}]   # scheduled
    news = [{"title": "Elite Dangerous: October Dev Log 2026 | Law & Disorder",
             "published_at": "2026-10-14T15:00:00+00:00",
             "field_slug": "elite-dangerous-october-dev-log-2026-law-disorder"}]
    with mock.patch.object(galnet_news.requests, "get", side_effect=[_resp(updates), _resp(news)]):
        got = galnet_news.fetch_frontier_notices(now=NOW)
    assert got == [
        ("Update notes 4.4.2.0: Elite Dangerous: Anaconda MK II Update (10-20)",
         "https://www.elitedangerous.com/news/updates/4-4-2-0"),
        ("Frontier news: Elite Dangerous: October Dev Log 2026 | Law & Disorder (10-14)",
         "https://www.elitedangerous.com/news/elite-dangerous-october-dev-log-2026-law-disorder")]


def test_fetch_failure_gives_nothing():
    with mock.patch.object(galnet_news.requests, "get", side_effect=OSError("down")):
        assert galnet_news.fetch_frontier_notices(now=NOW) == []


def test_game_version_change_is_reported_once(tmp_path):
    path = tmp_path / "game_version.json"
    assert note_game_version(path, "4.4.1.1") is None          # first run: just remembered
    assert note_game_version(path, "4.4.1.1") is None
    assert note_game_version(path, "4.4.2.0") == "4.4.1.1"
    assert note_game_version(path, "4.4.2.0") is None
    assert note_game_version(path, None) is None


def test_game_update_notice_leads_the_ticker_and_survives_a_refresh():
    from types import SimpleNamespace
    from edc.ui.main_window import MainWindow
    shown = []
    notice = ("Game updated 4.4.1.1 → 4.4.2.0: check the update notes", "https://www.elitedangerous.com/news/updates")
    fake = SimpleNamespace(_game_update_notice=notice, _galnet_headlines=[], _galnet_headline_index=3,
                           _show_galnet_headline=lambda: shown.append(fake._galnet_headlines[0]))
    MainWindow._on_galnet_refreshed(fake, [("GalNet story", None)])
    MainWindow._on_galnet_refreshed(fake, fake._galnet_headlines)         # re-shown: not doubled
    assert fake._galnet_headlines == [notice, ("GalNet story", None)] and shown[-1] == notice
