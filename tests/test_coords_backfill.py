"""Tests for the coordinate-backfill safety net: fetch_system_coords()'s
retry-on-blocked behavior, and Repository.get_faction_system_names_missing_coords()'s
query. Confirmed live: a real, resolvable system ("Ekono") failed a single
one-shot EDSM attempt during what was presumably a transient rate-limit/
Cloudflare blip -- fetch_system_coords used to have no retry at all."""
from unittest.mock import Mock, patch

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.core.edsm_faction_lookup import fetch_system_coords


def _fake_response(status_code=200, json_value=None):
    resp = Mock()
    resp.status_code = status_code
    if status_code == 200:
        resp.raise_for_status = Mock()
    else:
        resp.raise_for_status = Mock(side_effect=Exception(f"status {status_code}"))
    resp.json = Mock(return_value=json_value if json_value is not None else {})
    return resp


_COORDS_BODY = {"coords": {"x": 1.0, "y": 2.0, "z": 3.0}}


# --- fetch_system_coords() retry behavior ---

def test_succeeds_on_first_attempt_without_retry():
    # time.sleep is also used internally by the module's shared EDSM
    # request throttle (unrelated to retry backoff) and its gate state
    # persists across the whole test process, so this only asserts the
    # signal that actually matters here: exactly one HTTP attempt, not
    # whether time.sleep happened to fire for throttling reasons.
    with patch("edc.core.edsm_faction_lookup.requests.get", return_value=_fake_response(json_value=_COORDS_BODY)) as mock_get, \
         patch("edc.core.edsm_faction_lookup.time.sleep"):
        result = fetch_system_coords("Ekono")
    assert result == (1.0, 2.0, 3.0)
    assert mock_get.call_count == 1


def test_retries_after_a_transient_failure_then_succeeds():
    # First call raises (simulating a connection reset / EDSM block),
    # second call succeeds -- this is exactly the "Ekono" scenario:
    # a real, resolvable system failing its one-shot attempt.
    with patch(
        "edc.core.edsm_faction_lookup.requests.get",
        side_effect=[Exception("Connection aborted"), _fake_response(json_value=_COORDS_BODY)],
    ) as mock_get, patch("edc.core.edsm_faction_lookup.time.sleep"):
        result = fetch_system_coords("Ekono")
    assert result == (1.0, 2.0, 3.0)
    assert mock_get.call_count == 2


def test_gives_up_after_exhausting_retries_on_repeated_blocks():
    with patch(
        "edc.core.edsm_faction_lookup.requests.get",
        side_effect=Exception("Connection aborted"),
    ) as mock_get, patch("edc.core.edsm_faction_lookup.time.sleep"):
        result = fetch_system_coords("Ekono")
    assert result is None
    assert mock_get.call_count == 4  # 1 initial + 3 retries


def test_genuine_not_found_does_not_retry():
    # A valid EDSM response with no coords (system unknown to EDSM) is a
    # real answer, not a failure -- retrying it would waste the shared
    # EDSM request budget on something retries can never fix.
    with patch(
        "edc.core.edsm_faction_lookup.requests.get",
        return_value=_fake_response(json_value={}),
    ) as mock_get, patch("edc.core.edsm_faction_lookup.time.sleep"):
        result = fetch_system_coords("ThisSystemDoesNotExistAtAll12345XYZ")
    assert result is None
    assert mock_get.call_count == 1


# --- get_faction_system_names_missing_coords() ---

@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _track_system(repo, system_address, system_name, faction_name):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )
    repo.save_faction_snapshot(
        system_address, {"Name": faction_name, "Influence": 0.1}, "2026-08-25", False, "2026-08-25T00:00:00Z", "journal",
    )


def test_finds_tracked_system_with_no_coords_row(repo):
    _track_system(repo, 1, "Ekono", "Elite United Worlds")
    names = repo.get_faction_system_names_missing_coords("Elite United Worlds")
    assert names == ["Ekono"]


def test_excludes_system_that_already_has_coords(repo):
    _track_system(repo, 1, "Ekono", "Elite United Worlds")
    repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", ("Ekono", 1.0, 2.0, 3.0))
    names = repo.get_faction_system_names_missing_coords("Elite United Worlds")
    assert names == []


def test_excludes_other_factions_systems(repo):
    _track_system(repo, 1, "Ekono", "Some Rival Faction")
    names = repo.get_faction_system_names_missing_coords("Elite United Worlds")
    assert names == []


def test_respects_limit(repo):
    for i in range(5):
        _track_system(repo, i, f"System{i}", "Elite United Worlds")
    names = repo.get_faction_system_names_missing_coords("Elite United Worlds", limit=2)
    assert len(names) == 2
