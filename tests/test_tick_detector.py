"""Second tick source: a burst of systems changing influence in the EDDN feed
(tick.edcd.io listed no tick for 2026-10-18 while influence still moved)."""
from datetime import datetime, timedelta, timezone

from edc.core.tick_detector import MIN_SYSTEMS, TickDetector

T0 = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed(det, addr, inf, at, uploader=None):
    return det.observe(addr, [{"Name": "A", "Influence": inf}, {"Name": "B", "Influence": 1 - inf}], _iso(at), now=at,
                       uploader=uploader if uploader is not None else f"u{addr % 7}")


def test_burst_of_changes_is_a_tick():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    for a in range(MIN_SYSTEMS + 5):                                   # baseline before the tick
        assert _feed(det, a, 0.5, T0 + timedelta(minutes=a)) is None
    tick_at = T0 + timedelta(hours=1)
    found = [_feed(det, a, 0.51, tick_at + timedelta(minutes=a)) for a in range(MIN_SYSTEMS)]
    assert found[:-1] == [None] * (MIN_SYSTEMS - 1)
    assert found[-1] == _iso(tick_at)                                  # earliest change in the burst
    assert _feed(det, 99, 0.6, tick_at + timedelta(minutes=30)) is None   # no second tick right after


def test_unchanged_repeats_stale_messages_and_too_soon_are_ignored():
    det = TickDetector(last_tick=_iso(T0 - timedelta(hours=10)))      # last tick only 10 h ago
    for a in range(MIN_SYSTEMS + 5):
        _feed(det, a, 0.5, T0 + timedelta(minutes=a))
    later = T0 + timedelta(hours=1)
    assert all(_feed(det, a, 0.5, later) is None for a in range(MIN_SYSTEMS + 5))       # same levels
    assert all(_feed(det, a, 0.6, later + timedelta(minutes=1)) is None for a in range(MIN_SYSTEMS + 5))  # < 16 h
    old = T0 - timedelta(hours=2)                                        # a replayed old journal line
    assert det.observe(1, [{"Name": "A", "Influence": 0.9}], _iso(old), now=T0) is None


def test_one_uploader_cannot_fake_a_tick():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    for a in range(MIN_SYSTEMS + 5):
        _feed(det, a, 0.5, T0 + timedelta(minutes=a), uploader="faker")
    later = T0 + timedelta(hours=1)
    assert all(_feed(det, a, 0.9, later + timedelta(minutes=a), uploader="faker") is None
               for a in range(MIN_SYSTEMS + 5))


def test_same_tick_from_both_sources_is_stored_once(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-18T16:20:00Z", source="eddn")        # EDDN detector first
    repo.record_bgs_tick("2026-10-18T16:25:36+00:00")                  # tick.edcd.io, same tick: its time wins
    repo.record_bgs_tick("2026-10-18T18:00:00Z", source="eddn")        # a later detection can't move it
    repo.record_bgs_tick("2026-10-19T16:30:00Z")                       # next day
    assert repo.get_bgs_ticks() == ["2026-10-18T16:25:36Z", "2026-10-19T16:30:00Z"]
    db.close()
