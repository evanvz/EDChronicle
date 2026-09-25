"""MainWindow._record_faction_mission_completion() -- reads straight from
a MissionCompleted event's own FactionEffects array (no more pre-capture
from active_missions before engine.process() pops it). FactionEffects
lists every faction the mission actually moved, each with its own
SystemAddress (a secondary/target faction's bump can land in a different
system than the primary one -- e.g. the mission's destination) and an
Influence string whose length is Frontier's own "+" to "+++++" tier.
Primary = the effect on the mission's own issuing faction (evt['Faction']),
same split BGS-Tally uses. Fake self, same pattern as
test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self():
    saved = []
    notified = []
    return SimpleNamespace(
        repo=SimpleNamespace(record_faction_mission_completion=lambda **kw: saved.append(kw)),
        player_faction_panel=SimpleNamespace(notify_faction_mission_completed=lambda addr: notified.append(addr)),
        _saved=saved,
        _notified=notified,
    )


def _effect(faction, system_address, tier="++", trend="UpGood"):
    return {"Faction": faction, "Influence": [{"SystemAddress": system_address, "Trend": trend, "Influence": tier}]}


def test_primary_effect_is_recorded():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_Courier_Boom_name",
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [{
        "system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
        "influence_tier": "++", "is_primary": True, "mission_type": "Courier Boom",
    }]
    assert fake_self._notified == [12345]


def test_secondary_effect_is_recorded_separately_even_in_a_different_system():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_Courier_name",
        "FactionEffects": [
            _effect("Hungarian Wolves", 999, tier="++"),  # target faction, destination system
            _effect("Elite United Worlds", 12345, tier="++"),  # issuer, current system
        ],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [
        {"system_address": 999, "faction_name": "Hungarian Wolves", "completed_at": "2026-09-24T10:00:00Z",
         "influence_tier": "++", "is_primary": False, "mission_type": "Courier"},
        {"system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
         "influence_tier": "++", "is_primary": True, "mission_type": "Courier"},
    ]
    assert set(fake_self._notified) == {999, 12345}


def test_missing_name_field_yields_no_mission_type():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved[0]["mission_type"] is None


def test_missing_faction_effects_is_skipped():
    fake_self = _fake_self()
    evt = {"event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []
    assert fake_self._notified == []


def test_effect_with_no_influence_entries_is_skipped():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [{"Faction": "Elite United Worlds", "Influence": []}],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []
    assert fake_self._notified == []


def test_effect_missing_faction_name_is_skipped():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [{"Influence": [{"SystemAddress": 12345, "Influence": "++"}]}],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []


def test_missing_timestamp_falls_back_to_now():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds",
        "FactionEffects": [_effect("Elite United Worlds", 12345)],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert len(fake_self._saved) == 1
    assert fake_self._saved[0]["completed_at"]  # non-empty ISO string
