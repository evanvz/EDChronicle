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


def _baseline(det, n, inf=0.5, uploader=None):
    for a in range(n):                                     # pre-tick lull: same values, several hours
        for h in (0, 1, 2, 3, 4, 5):
            _feed(det, a, inf, T0 + timedelta(hours=h, minutes=a), uploader)


def test_burst_of_changes_is_a_tick():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, MIN_SYSTEMS + 5)
    tick_at = T0 + timedelta(hours=6)
    found = [_feed(det, a, 0.51, tick_at + timedelta(minutes=a)) for a in range(MIN_SYSTEMS)]
    assert found[:-1] == [None] * (MIN_SYSTEMS - 1)
    assert found[-1] == _iso(tick_at)                                  # earliest change in the burst
    assert _feed(det, 99, 0.6, tick_at + timedelta(minutes=30)) is None   # no second tick right after


def test_stale_uploads_flip_flopping_after_a_tick_are_not_a_new_tick():
    """EDCAS: for hours after a tick some uploaders still send the old values. Against
    a settled 2 h+ reference these don't look like a fresh burst."""
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, MIN_SYSTEMS + 5)
    tick_at = T0 + timedelta(hours=6)
    assert [_feed(det, a, 0.51, tick_at + timedelta(minutes=a)) for a in range(MIN_SYSTEMS)][-1] == _iso(tick_at)
    # old and new values keep alternating from the tick for the next 30 hours
    flips = [_feed(det, a, 0.50 if h % 2 else 0.51, tick_at + timedelta(hours=h, minutes=a))
             for h in range(1, 31) for a in range(MIN_SYSTEMS + 5)]
    assert not any(flips)                                             # never a quiet lull -> no false tick


def test_small_moves_do_not_count():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, MIN_SYSTEMS + 5)
    assert not any(_feed(det, a, 0.503, T0 + timedelta(hours=6, minutes=a)) for a in range(MIN_SYSTEMS + 5))


def test_unchanged_repeats_stale_messages_and_too_soon_are_ignored():
    det = TickDetector(last_tick=_iso(T0 - timedelta(hours=4)))       # last tick only 10 h before the changes
    _baseline(det, MIN_SYSTEMS + 5)
    later = T0 + timedelta(hours=6)
    assert all(_feed(det, a, 0.5, later) is None for a in range(MIN_SYSTEMS + 5))       # same levels
    assert all(_feed(det, a, 0.6, later + timedelta(minutes=1)) is None for a in range(MIN_SYSTEMS + 5))  # < 12 h
    old = T0 - timedelta(hours=2)                                        # a replayed old journal line
    assert det.observe(1, [{"Name": "A", "Influence": 0.9}], _iso(old), now=T0) is None


def test_one_uploader_cannot_fake_a_tick():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, MIN_SYSTEMS + 5, uploader="faker")
    later = T0 + timedelta(hours=6)
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


def test_one_uploader_spamming_the_lull_cannot_suppress_a_real_tick():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, MIN_SYSTEMS + 5)
    spam_at = T0 + timedelta(hours=3)
    for a in range(100, 110):                       # fake changes in the lull, all from one sender
        _feed(det, a, 0.5, spam_at - timedelta(hours=3), uploader="spammer")
        _feed(det, a, 0.9, spam_at + timedelta(minutes=a - 100), uploader="spammer")
    tick_at = T0 + timedelta(hours=6)
    found = [_feed(det, a, 0.51, tick_at + timedelta(minutes=a)) for a in range(MIN_SYSTEMS)]
    assert found[-1] == _iso(tick_at)


def test_snapshot_reports_biggest_burst_and_why_it_stopped():
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    _baseline(det, 5)
    for a in range(5):
        _feed(det, a, 0.6, T0 + timedelta(hours=6, minutes=a))
    assert det.snapshot().endswith("biggest burst 5 systems / 5 uploaders in 60 min (too few)")
    assert "biggest burst 0 systems" in det.snapshot()          # reset after each report


def test_no_tick_until_the_quiet_spell_was_watched():
    """10-22 17:11: restarted at 15:12, blind for 2 h, so the 3 h 'lull' was unseen."""
    det = TickDetector(last_tick="2026-10-17T16:25:36Z")
    for a in range(MIN_SYSTEMS + 5):            # watched from T0, for 3 h only
        for h in (0, 1, 2, 3):
            _feed(det, a, 0.5, T0 + timedelta(hours=h, minutes=a))
    early = T0 + timedelta(hours=4)             # lull 1..4 h: the first 2 h were blind
    assert not any(_feed(det, a, 0.51, early + timedelta(minutes=a)) for a in range(MIN_SYSTEMS + 5))
    assert det.snapshot().endswith("(still warming up)")
