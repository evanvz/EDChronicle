"""Second tick source: an hour in which far more systems change influence than
usual, in the EDDN feed (redesigned 2026-10-23: relative to the usual share,
no fixed system count or quiet-spell rule, state kept across restarts)."""
from datetime import datetime, timedelta, timezone

from edc.core.tick_detector import TickDetector

T0 = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
N = 200                                           # systems in the feed


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed(det, addr, inf, at, uploader=None):
    return det.observe(addr, [{"Name": "A", "Influence": inf}, {"Name": "B", "Influence": 1 - inf}], _iso(at), now=at,
                       uploader=uploader if uploader is not None else f"u{addr % 7}")


def _hours(det, first, last, level, background=2, start_level=None):
    """Every system read once an hour; `background` systems a hour drift (late
    updates, stale uploads), as the real feed does. level(a, h) gives the rest."""
    found = []
    for h in range(first, last):
        for a in range(N):
            inf = level(a, h)
            if a < background * h:                 # each hour a few more systems have drifted
                inf += 0.02
            found.append(_feed(det, a, inf, T0 + timedelta(hours=h, minutes=a % 60)))
    return [f for f in found if f]


def test_burst_well_above_the_usual_share_is_a_tick():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    assert _hours(det, 0, 8, lambda a, h: 0.5) == []                       # background only
    tick = T0 + timedelta(hours=8)
    found = _hours(det, 8, 9, lambda a, h: 0.55 if a % 3 == 0 else 0.5)   # a third of the systems move
    assert found and found[0] == _iso(tick)                                 # earliest change in the burst
    assert "(tick)" in det.snapshot()


def test_steady_background_is_never_a_tick():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    assert _hours(det, 0, 20, lambda a, h: 0.5, background=8) == []        # 8 a hour, every hour


def test_no_tick_before_the_usual_share_is_known():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    assert _hours(det, 0, 4, lambda a, h: 0.5 if h < 3 else 0.6) == []    # burst in hour 3: no baseline yet
    assert "learning the usual share" in det.snapshot()


def test_small_moves_do_not_count():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    assert _hours(det, 0, 9, lambda a, h: 0.5 if h < 8 else 0.503, background=0) == []


def test_one_uploader_cannot_fake_a_tick():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    _hours(det, 0, 8, lambda a, h: 0.5)
    at = T0 + timedelta(hours=8)
    assert not any(_feed(det, a, 0.9, at + timedelta(seconds=a), uploader="faker") for a in range(N))


def test_too_soon_after_the_last_tick():
    det = TickDetector(last_tick=_iso(T0))
    _hours(det, 0, 8, lambda a, h: 0.5)
    assert _hours(det, 8, 9, lambda a, h: 0.6) == []                       # 8 h after a tick
    assert "too soon" in det.snapshot()


def test_stale_flip_flops_after_a_tick_are_not_another_tick():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    _hours(det, 0, 8, lambda a, h: 0.5)
    first = _hours(det, 8, 9, lambda a, h: 0.6)
    later = _hours(det, 9, 19, lambda a, h: 0.5 if h % 2 else 0.6)        # old and new values keep alternating
    assert len(first) == 1 and later == []


def test_state_survives_a_restart(tmp_path):
    path = tmp_path / "state.json.gz"
    det = TickDetector(last_tick="2026-10-21T03:49:58Z", state_path=path)
    _hours(det, 0, 8, lambda a, h: 0.5)
    det.save(T0 + timedelta(hours=8))
    again = TickDetector(last_tick="2026-10-21T03:49:58Z", state_path=path)   # restarted
    found = _hours(again, 8, 9, lambda a, h: 0.55 if a % 3 == 0 else 0.5)
    assert found and found[0] == _iso(T0 + timedelta(hours=8))           # no blind warm-up
    broken = tmp_path / "broken.json.gz"
    broken.write_bytes(b"not gzip")
    assert TickDetector(state_path=broken).observe(1, [{"Name": "A", "Influence": 0.5}],
                                                   _iso(T0), now=T0) is None   # bad file: starts empty


def test_same_tick_from_both_sources_is_stored_once(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.record_bgs_tick("2026-10-18T16:20:00Z", source="eddn")        # EDDN detector first
    assert repo.get_tick_info(1)[0]["confirmed"] is False
    repo.record_bgs_tick("2026-10-18T16:25:36+00:00")                  # tick.edcd.io, same tick: its time wins
    repo.record_bgs_tick("2026-10-18T18:00:00Z", source="eddn")        # a later detection can't move it
    repo.record_bgs_tick("2026-10-19T16:30:00Z")                       # next day
    assert repo.get_bgs_ticks() == ["2026-10-18T16:25:36Z", "2026-10-19T16:30:00Z"]
    assert all(t["confirmed"] for t in repo.get_tick_info(5))
    db.close()


def test_a_wave_of_updates_after_the_tick_confirms_it():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    _hours(det, 0, 8, lambda a, h: 0.5)
    assert _hours(det, 8, 9, lambda a, h: 0.55 if a % 4 == 0 else 0.5)
    # systems keep updating over the next hours, a different quarter each hour
    _hours(det, 9, 14, lambda a, h: 0.55 + (0.02 * h if a % 4 == h % 4 else 0) if a % 4 == 0 or a % 4 <= h - 8 else 0.5)
    assert det.pop_confirmed() == _iso(T0 + timedelta(hours=8))
    assert det.pop_confirmed() is None                                    # reported once


def test_a_blip_without_a_wave_stays_unconfirmed():
    det = TickDetector(last_tick="2026-10-21T03:49:58Z")
    _hours(det, 0, 8, lambda a, h: 0.5)
    assert _hours(det, 8, 9, lambda a, h: 0.55 if a % 3 == 0 else 0.5)
    _hours(det, 9, 23, lambda a, h: 0.55 if a % 3 == 0 else 0.5)          # nothing more changes
    assert det.pop_confirmed() is None and det._wave is None              # judged, left unconfirmed
