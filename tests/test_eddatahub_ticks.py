"""EDDataHub (the squadron's 24/7 LAN service) as the BGS tick source: its
ticks replace our own detections, our EDDN detector stands by while it answers,
and the status bar shows which one is in use."""
from types import SimpleNamespace
from unittest import mock

from edc.core import eddatahub_client
from edc.ui.main_window import MainWindow


def test_hub_ticks_parsed_and_offline_is_none():
    resp = mock.Mock(status_code=200)
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"tick": "2026-10-22T17:02:11+00:00", "source": "feed"},
                              {"tick": "2026-10-23T16:10:36.120+00:00", "source": "inferred"}]
    with mock.patch.object(eddatahub_client.requests, "get", return_value=resp):
        assert eddatahub_client.fetch_ticks("http://hub:8080") == ["2026-10-22T17:02:11Z", "2026-10-23T16:10:36Z"]
    with mock.patch.object(eddatahub_client.requests, "get", side_effect=OSError("no route")):
        assert eddatahub_client.fetch_ticks("http://hub:8080") is None
    assert eddatahub_client.fetch_ticks("") is None


def test_hub_tick_replaces_our_detected_one(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-23T18:21:20Z", source="eddn")       # our late, post-restart guess
    repo.record_bgs_tick("2026-10-23T16:10:36Z", source="hub")
    assert repo.get_tick_info(1)[0] == {"at": "2026-10-23T16:10:36Z", "source": "hub", "upper": None,
                                        "confirmed": True}
    db.close()


def _label():
    styles = {}
    lbl = SimpleNamespace(setStyleSheet=lambda s: styles.__setitem__("s", s), setToolTip=lambda t: None)
    return lbl, styles


def test_status_bar_and_own_detection_follow_the_hub():
    hub, hub_style = _label()
    own, own_style = _label()
    recorded = []
    win = SimpleNamespace(_hub_label=hub, _service_health_labels={"BGS Tick": own}, _hub_active=False,
                          repo=SimpleNamespace(record_bgs_tick=lambda *a, **k: recorded.append(a)),
                          _on_bgs_tick_check_finished=lambda t: None)
    win._on_service_health_tick = lambda: MainWindow._on_service_health_tick(win)
    MainWindow._set_hub_status(win, True)
    assert "#6BCB77" in hub_style["s"] and "#555555" in own_style["s"]          # hub green, own greyed
    MainWindow._on_eddn_tick_detected(win, "2026-10-24T06:25:08Z")
    assert recorded == []                                                        # own detection stands by
    MainWindow._set_hub_status(win, False)
    assert "#888888" in hub_style["s"] and "#555555" not in own_style["s"]
    MainWindow._on_eddn_tick_detected(win, "2026-10-24T06:25:08Z")
    assert recorded                                                              # fallback in use


def test_hub_is_opt_in_and_odd_answers_are_rejected():
    from datetime import datetime, timedelta, timezone
    from edc.config import AppConfig
    assert AppConfig().eddatahub_url == ""                                     # public installs: off
    now = datetime.now(timezone.utc)
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"tick": (now - timedelta(days=1)).isoformat()},
                              {"tick": (now + timedelta(days=1)).isoformat()},   # future: dropped
                              {"tick": (now - timedelta(days=90)).isoformat()}]  # outside the window: dropped
    with mock.patch.object(eddatahub_client.requests, "get", return_value=resp):
        assert len(eddatahub_client.fetch_ticks("http://hub:8080")) == 1
    resp.json.return_value = [{"tick": now.isoformat()}] * 500                   # flood
    with mock.patch.object(eddatahub_client.requests, "get", return_value=resp):
        assert eddatahub_client.fetch_ticks("http://hub:8080") is None


def test_system_ticks_from_the_hub_settle_readings(tmp_path):
    """VE-Q: a reading 5 h after the tick is provisional under the 22 h allowance,
    but settled once EDDataHub says the tick showed in its reports at 4 h."""
    from edc.core.bgs_experiment import build_rows
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"system": 7, "tick": "2026-10-23T16:10:36+00:00", "last_before": "2026-10-23T15:00:00+00:00",
                               "first_after": "2026-10-23T20:00:00+00:00", "status": "seen"},
                              {"system": 99, "tick": "2026-10-23T16:10:36+00:00", "last_before": "2026-10-23T15:00:00+00:00",
                               "first_after": "2026-10-23T20:00:00+00:00", "status": "seen"}]   # not asked for
    with mock.patch.object(eddatahub_client.requests, "get", return_value=resp):
        rows = eddatahub_client.fetch_system_ticks("http://hub:8080", [7])
    assert rows == [(7, "2026-10-23T16:10:36Z", "2026-10-23T15:00:00Z", "2026-10-23T20:00:00Z", "seen")]
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.save_hub_system_ticks(rows)
    reached = repo.get_hub_system_ticks(7)
    assert reached == {"2026-10-23T16:10:36Z": "2026-10-23T20:00:00Z"}
    effort = lambda s, e: {"tier_score": 0, "bounties": 0, "trade_profit": 0, "exploration": 0}
    readings = [("2026-10-23T21:00:00Z", 0.6438, None, None)]
    ticks = ["2026-10-23T16:10:36Z"]
    assert build_rows(ticks, readings, effort, now="2026-10-23T22:00:00Z")[0]["provisional"]
    assert not build_rows(ticks, readings, effort, now="2026-10-23T22:00:00Z", reached=reached)[0]["provisional"]
    db.close()
