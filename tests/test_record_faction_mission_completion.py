"""MainWindow._record_faction_mission_completion() -- reads straight from
a MissionCompleted event's own FactionEffects array (no more pre-capture
from active_missions before engine.process() pops it). FactionEffects
lists every faction the mission actually moved, each with its own
SystemAddress (a secondary/target faction's bump can land in a different
system than the primary one -- e.g. the mission's destination) and an
Influence string whose length is Frontier's own "+" to "+++++" tier.
Primary = the effect on the mission's own issuing faction (evt['Faction']),
same split BGS-Tally uses.

Not every mission moves a faction's influence -- a pure cargo/passenger
mission can complete with no FactionEffects/Influence at all. A fallback
guarantees one is_primary row still gets written for the issuing faction
at the player's current system in that case, so "no BGS impact" is
recorded rather than the mission vanishing entirely. Fake self, same
pattern as test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345):
    saved = []
    notified = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address),
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
        "Name": "Mission_Courier_Boom_name", "Reward": 48200,
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [{
        "system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
        "influence_tier": "++", "is_primary": True, "mission_type": "Courier Boom", "reward": 48200,
    }]
    assert fake_self._notified == [12345]


def test_secondary_effect_is_recorded_separately_even_in_a_different_system():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_Courier_name", "Reward": 15000,
        "FactionEffects": [
            _effect("Hungarian Wolves", 999, tier="++"),  # target faction, destination system
            _effect("Elite United Worlds", 12345, tier="++"),  # issuer, current system
        ],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [
        {"system_address": 999, "faction_name": "Hungarian Wolves", "completed_at": "2026-09-24T10:00:00Z",
         "influence_tier": "++", "is_primary": False, "mission_type": "Courier", "reward": 15000},
        {"system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
         "influence_tier": "++", "is_primary": True, "mission_type": "Courier", "reward": 15000},
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


def test_camelcase_internal_name_gets_word_boundaries_split():
    """Confirmed live 2026-09-25: "Mission_AltruismCredits_name" has no
    underscore between "Altruism" and "Credits" at all, so the plain
    underscore-replace alone left it as one unbroken word in the report."""
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_AltruismCredits_name",
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved[0]["mission_type"] == "Altruism Credits"


def test_plain_single_word_internal_name_is_unchanged():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_Collect_name",
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved[0]["mission_type"] == "Collect"


def test_missing_reward_field_yields_no_reward():
    fake_self = _fake_self()
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [_effect("Elite United Worlds", 12345, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved[0]["reward"] is None


# --- no-BGS-impact fallback: still record a row for the issuing faction ---

def test_missing_faction_effects_falls_back_to_the_current_system():
    fake_self = _fake_self(system_address=12345)
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Name": "Mission_Delivery_name", "Reward": 5000,
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == [{
        "system_address": 12345, "faction_name": "Elite United Worlds", "completed_at": "2026-09-24T10:00:00Z",
        "influence_tier": None, "is_primary": True, "mission_type": "Delivery", "reward": 5000,
    }]
    assert fake_self._notified == [12345]


def test_effect_with_no_influence_entries_falls_back_to_the_current_system():
    fake_self = _fake_self(system_address=12345)
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [{"Faction": "Elite United Worlds", "Influence": []}],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert len(fake_self._saved) == 1
    assert fake_self._saved[0]["system_address"] == 12345
    assert fake_self._saved[0]["is_primary"] is True
    assert fake_self._saved[0]["influence_tier"] is None
    assert fake_self._notified == [12345]


def test_secondary_only_effects_still_get_a_primary_fallback_row():
    """A mission whose FactionEffects only ever names a different (target)
    faction -- the issuing faction itself never appears -- must still get
    its own is_primary row via the fallback, or its reward/type would be
    invisible to get_session_activity_report()'s is_primary-only reward sum."""
    fake_self = _fake_self(system_address=12345)
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "Reward": 7000,
        "FactionEffects": [_effect("Hungarian Wolves", 999, tier="++")],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert len(fake_self._saved) == 2
    primary_rows = [r for r in fake_self._saved if r["is_primary"]]
    assert len(primary_rows) == 1
    assert primary_rows[0]["system_address"] == 12345
    assert primary_rows[0]["faction_name"] == "Elite United Worlds"
    assert primary_rows[0]["reward"] == 7000


def test_effect_missing_faction_name_falls_back_to_the_current_system():
    fake_self = _fake_self(system_address=12345)
    evt = {
        "event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z",
        "FactionEffects": [{"Influence": [{"SystemAddress": 12345, "Influence": "++"}]}],
    }
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert len(fake_self._saved) == 1
    assert fake_self._saved[0]["faction_name"] == "Elite United Worlds"


def test_fallback_skipped_without_a_current_system_address():
    fake_self = _fake_self(system_address=None)
    evt = {"event": "MissionCompleted", "Faction": "Elite United Worlds", "timestamp": "2026-09-24T10:00:00Z"}
    MainWindow._record_faction_mission_completion(fake_self, evt)
    assert fake_self._saved == []
    assert fake_self._notified == []


def test_fallback_skipped_without_an_issuing_faction():
    fake_self = _fake_self(system_address=12345)
    evt = {"event": "MissionCompleted", "timestamp": "2026-09-24T10:00:00Z"}
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
