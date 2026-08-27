"""Tests for bounty_age_days() -- confirms UTC-correct parsing. Previously
duplicated in two panels as time.mktime(time.strptime(ts, ...)), which
misinterprets the naive struct_time as LOCAL time even though the string
itself is UTC ("...Z") -- correct on a UTC-local test machine by
coincidence, wrong everywhere else. This uses the same fromisoformat-based
UTC-aware approach as formatting.py's own relative_time(), so it's
correct regardless of the machine's local timezone, not just accidentally
correct here."""
from datetime import datetime, timedelta, timezone

from edc.ui.formatting import bounty_age_days


def test_returns_none_for_empty_string():
    assert bounty_age_days("") is None


def test_returns_none_for_malformed_timestamp():
    assert bounty_age_days("not a timestamp") is None


def test_zero_age_for_current_timestamp():
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = bounty_age_days(now_iso)
    assert age is not None
    assert age < 0.001  # well under a second, expressed in days


def test_six_days_ago_is_close_to_six():
    ts = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = bounty_age_days(ts)
    assert age is not None
    assert 5.99 <= age <= 6.01


def test_age_never_negative_for_a_future_timestamp():
    # Defensive: a clock-skew edge case should clamp to 0, not go negative
    # (a negative age would incorrectly read as "not yet dormant" logic
    # elsewhere assumes a non-negative day count).
    future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = bounty_age_days(future_ts)
    assert age == 0.0
