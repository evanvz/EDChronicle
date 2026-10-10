"""expansion_endings(): days an expansion finished, with the influence
change. Ekono / Elite United Worlds,
from the app's own snapshots 2026-09-22..10-07."""
from edc.ui.panels.faction_expansion_dialog import expansion_endings


def _snap(date, inf, state=None, active=None, rec=None):
    return {"snapshot_date": date, "influence": inf, "faction_state": state, "active_states": active,
            "recovering_states": rec}


R = '[{"State": "Expansion", "Trend": 0}]'


def test_ekono_two_expansion_endings():
    hist = [
        _snap("2026-09-22", 0.829871, "Expansion", '[{"State": "Expansion"}]'),
        _snap("2026-09-23", 0.681503, "Expansion", None, R),   # state still reads Expansion
        _snap("2026-09-24", 0.70297, None, None, R),
        _snap("2026-09-27", 0.774, "Boom", '[{"State": "Boom"}]'),
        _snap("2026-10-02", 0.8091, "Expansion", '[{"State": "Boom"}, {"State": "Expansion"}]'),
        _snap("2026-10-06", 0.7895, "Expansion", '[{"State": "Expansion"}]'),
        _snap("2026-10-07", 0.6789, None, None, R),
    ]
    got = expansion_endings(hist)
    assert [(i, d) for i, d, _ in got] == [(1, "2026-09-23"), (6, "2026-10-07")]
    assert round(got[0][2], 1) == -14.8 and round(got[1][2], 1) == -11.1


def test_no_expansion_no_events():
    assert expansion_endings([_snap("a", 0.5), _snap("b", 0.4)]) == []
