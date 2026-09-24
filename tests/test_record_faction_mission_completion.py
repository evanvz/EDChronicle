"""MainWindow._record_faction_mission_completion() -- captures a
MissionCompleted event's faction/system before active_missions discards
that mission's record entirely (event_engine.py's apply_mission_event
pops it on MissionCompleted). Fake self, same pattern as
test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345):
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address),
        repo=SimpleNamespace(record_faction_mission_completion=lambda **kw: saved.append(kw)),
        _saved=saved,
    )


def test_completed_mission_is_recorded():
    fake_self = _fake_self()
    evt = {"event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [{
        "system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
    }]


def test_missing_faction_field_is_skipped():
    fake_self = _fake_self()
    evt = {"event": "MissionCompleted", "timestamp": "2026-09-24T10:00:00Z"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []


def test_missing_system_address_is_skipped():
    fake_self = _fake_self(system_address=None)
    evt = {"event": "MissionCompleted", "Faction": "Elite United Worlds"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []


def test_missing_timestamp_falls_back_to_now():
    fake_self = _fake_self()
    evt = {"event": "MissionCompleted", "Faction": "Elite United Worlds"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert len(fake_self._saved) == 1
    assert fake_self._saved[0]["faction_name"] == "Elite United Worlds"
    assert fake_self._saved[0]["completed_at"]  # non-empty ISO string
