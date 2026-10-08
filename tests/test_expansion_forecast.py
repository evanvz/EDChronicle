"""Expansion Forecast rules (edc/core/expansion_forecast.py). Real data from
2026-10-07/08: Ekono expanded into Tucanae Sector YF-W b2-2; Arimavante was
closer with 6 factions but was skipped (likely an earlier EUW retreat)."""
from datetime import date

from edc.core import expansion_forecast as ef

R = '[{"State": "Expansion", "Trend": 0}]'
TODAY = date(2026, 10, 8)


def _p(addr, name, inf, first, last, **states):
    return {"system_address": addr, "system_name": name, "influence": inf, "first_seen": first,
            "last_seen": last, "faction_state": states.get("state"), "active_states": states.get("active"),
            "pending_states": states.get("pending"), "recovering_states": states.get("rec")}


def test_in_cube_uses_each_axis_not_straight_line():
    ekono = (59.125, -155.15625, 99.8125)
    yfw = (39.46875, -163.9375, 117.96875)            # 28.2 ly away, every axis under 20
    assert ef.in_cube(ekono, yfw)
    assert not ef.in_cube(ekono, (59.125 + 21, -155.15625, 99.8125))


def test_days_at_or_above_counts_the_latest_run():
    hist = [{"influence": 0.80}, {"influence": 0.70}, {"influence": 0.76}, {"influence": 0.79}]
    assert ef.days_at_or_above(hist) == 2
    assert ef.days_at_or_above([{"influence": 0.6}]) == 0


def test_expansion_phase():
    assert ef.expansion_phase({"pending_states": R}) == "pending"
    assert ef.expansion_phase({"faction_state": "Expansion", "active_states": '[{"State": "Expansion"}]'}) == "active"
    # 2026-09-23: state still read Expansion but it was recovering
    assert ef.expansion_phase({"faction_state": "Expansion", "recovering_states": R}) == "recovering"
    assert ef.expansion_phase({}) == ""


def test_watched_and_likely_source():
    presence = [_p(1, "Ekono", 0.7895, "2026-09-08", "2026-10-06"),
                _p(2, "Other", 0.72, "2026-09-08", "2026-10-07"),
                _p(3, "Low", 0.40, "2026-09-08", "2026-10-07"),
                _p(4, "Left long ago", 0.90, "2026-08-01", "2026-08-20")]   # not current
    hist = {1: [{"influence": 0.80}, {"influence": 0.7895}], 2: [{"influence": 0.72}]}
    watched = ef.watched_systems(presence, hist, TODAY)
    assert [w["system_name"] for w in watched] == ["Ekono", "Other"]
    src = ef.likely_source(watched)
    assert src["system_name"] == "Ekono" and src["eligible"] is True
    only_low = ef.watched_systems([_p(2, "Other", 0.72, "2026-09-08", "2026-10-07")], {2: [{"influence": 0.72}]}, TODAY)
    assert ef.likely_source(only_low)["eligible"] is False
    assert ef.likely_source([]) is None


def test_old_or_zero_rows_are_not_current():
    assert not ef.is_current(_p(1, "A", 0.5, "2026-08-01", "2026-09-01"), TODAY)   # last seen > 14 days ago
    assert not ef.is_current(_p(1, "A", 0.0, "2026-08-01", "2026-10-07"), TODAY)   # influence 0 = left
    assert ef.is_current(_p(1, "A", 0.5, "2026-08-01", "2026-10-07"), TODAY)


def test_rank_candidates_tiers_and_order():
    cands = [
        {"system_name": "YF-W", "distance_ly": 28.2, "faction_count": 4, "faction_present": False, "been_before": False},
        {"system_name": "Arimavante", "distance_ly": 10.9, "faction_count": 6, "faction_present": False, "been_before": False},
        {"system_name": "Left before", "distance_ly": 5.0, "faction_count": 5, "faction_present": False, "been_before": True},
        {"system_name": "Seven", "distance_ly": 3.0, "faction_count": 7, "faction_present": False, "been_before": False},
        {"system_name": "Eight", "distance_ly": 2.0, "faction_count": 8, "faction_present": False, "been_before": False},
        {"system_name": "Here now", "distance_ly": 1.0, "faction_count": 3, "faction_present": True, "been_before": False},
        {"system_name": "Not checked", "distance_ly": 4.0, "faction_count": None, "faction_present": False, "been_before": False},
    ]
    out = ef.rank_candidates(cands)
    assert [(c["system_name"], c["tier"]) for c in out] == [
        ("Arimavante", 1), ("YF-W", 1), ("Left before", 2), ("Seven", 3), ("Not checked", None)]


def test_new_system_paired_with_expansion_ending():
    presence = [_p(2, "Tucanae Sector YF-W b2-2", 0.090992, "2026-10-07", "2026-10-07"),
                _p(1, "Ekono", 0.6789, "2026-09-08", "2026-10-07")]
    out = ef.new_systems(presence, [("Ekono", "2026-10-07")], TODAY)
    assert out == [{"system_name": "Tucanae Sector YF-W b2-2", "influence": 0.090992,
                    "first_seen": "2026-10-07", "source": "Ekono"}]
    assert ef.alert_text("Elite United Worlds", out[0]) == (
        "🆕 Elite United Worlds entered Tucanae Sector YF-W b2-2 (9.1%) — likely expansion from Ekono")


def test_new_system_rules_out_old_large_and_zero():
    presence = [_p(1, "Old", 0.09, "2026-10-01", "2026-10-07"),           # first seen 7 days ago
                _p(2, "Long held, first fetch", 0.45, "2026-10-08", "2026-10-08"),   # over the 20% cap
                _p(3, "Left", 0.0, "2026-10-08", "2026-10-08")]
    assert ef.new_systems(presence, [], TODAY) == []
    lone = ef.new_systems([_p(4, "No source", 0.05, "2026-10-08", "2026-10-08")], [], TODAY)
    assert lone[0]["source"] is None
    assert ef.alert_text("EUW", lone[0]) == "🆕 EUW entered No source (5.0%)"
