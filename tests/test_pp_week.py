from datetime import datetime, timezone

from edc.core.pp_week import daily, last_24h, merge
from tests.test_pp_control_history import EKONO, _repo

WS = "2026-10-22T07:00:00Z"          # Thursday reset
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def rd(t, u, r=0, src="eddn"):
    return {"observed_at": t, "pp_state": "Exploited", "reinforcement": r, "undermining": u,
            "control": 0.3, "source": src}


def test_merge_dedupes_keeping_local():
    a = rd("2026-10-23T10:00:00Z", 5, src="journal")
    assert merge([a], [rd("2026-10-23T10:00:00Z", 5, src="hub"), rd("2026-10-24T10:00:00Z", 9, src="hub")]) \
        == [a, rd("2026-10-24T10:00:00Z", 9, src="hub")]


def test_daily_reset_day_from_zero_gap_day_none_and_span():
    days = daily([rd("2026-10-21T23:00:00Z", 999),                 # before the reset: ignored
                  rd("2026-10-22T09:00:00Z", 100, 10),
                  rd("2026-10-22T20:00:00Z", 120, 15),
                  rd("2026-10-25T08:00:00Z", 300, 40)], WS, NOW)
    assert [d["day"].isoformat() for d in days] == ["2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"]
    assert (days[0]["u"], days[0]["r"], days[0]["spans"]) == (120, 15, 1)
    assert days[1]["u"] is None and days[1]["state"] is None
    assert (days[3]["u"], days[3]["r"], days[3]["spans"]) == (180, 25, 3)
    assert days[4]["u"] is None


def test_daily_none_undermining_stays_none():
    r = rd("2026-10-23T10:00:00Z", None, 50)
    days = daily([rd("2026-10-22T10:00:00Z", 10), r, rd("2026-10-24T10:00:00Z", 30)], WS, NOW)
    assert days[1]["u"] is None and days[1]["r"] == 50
    assert days[2]["u"] == 20 and days[2]["spans"] == 2


def test_daily_first_reading_after_reset_day_spans_back_to_reset():
    days = daily([rd("2026-10-24T10:00:00Z", 25000), rd("2026-10-25T10:00:00Z", 25100)], WS, NOW)
    assert (days[2]["u"], days[2]["spans"]) == (25000, 3)           # Sat measured from the Thu reset
    assert (days[3]["u"], days[3]["spans"]) == (100, 1)


def test_daily_spans_tracked_per_key():
    days = daily([rd("2026-10-22T10:00:00Z", 100, 10), rd("2026-10-23T10:00:00Z", None, 20),
                  rd("2026-10-24T10:00:00Z", 150, 30)], WS, NOW)
    assert (days[2]["u"], days[2]["spans"], days[2]["r"], days[2]["spans_r"]) == (50, 2, 10, 1)


def test_last_24h():
    rs = [rd("2026-10-25T08:00:00Z", 300), rd("2026-10-26T10:00:00Z", 420)]
    assert last_24h(rs, WS, NOW) == (120, "up")
    assert last_24h(rs[1:], WS, NOW) is None                         # nothing 24 h old
    assert last_24h(rs[:1], WS, NOW) is None                         # nothing in the last 24 h


def test_get_pp_control_since(tmp_path):
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-10-21T10:00:00Z", "Stronghold", 1, 2, 0.3, "journal")
    repo.record_pp_control(EKONO, "2026-10-23T10:00:00Z", "Stronghold", 3, 4, 0.3, "journal")
    rows = repo.get_pp_control_since(EKONO, WS)
    assert [r["observed_at"] for r in rows] == ["2026-10-23T10:00:00Z"]
    assert isinstance(rows[0], dict) and rows[0]["undermining"] == 4
