"""Squadron "Hinder <faction>" objectives: push a faction's influence down."""
import json
from datetime import date

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, STATUS_DROPPING, STATUS_TODO, TASK_TYPES, build_task_view, validate_task_input,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task():
    return {"id": 1, "system_address": 1, "system_name": "Ekono", "task_type": "hinder",
            "faction_name": "Rival Front", "opponent_name": None, "note": None, "sort_order": 0,
            "created_at": "2026-10-02T00:00:00Z", "pp_mode": None}


def _hist(*pairs, active=()):
    return [{"faction_name": "Rival Front", "snapshot_date": d, "influence": inf,
             "active_states": json.dumps([{"State": s} for s in active]), "pending_states": "[]"}
            for d, inf in pairs]


def _report(weighted=0, profit=0):
    entry = {"missions": {"count": 1, "weighted": weighted}, "combat_bonds_total": 0, "bounties_total": 0,
             "cz_kills": {}, "trade_sold": {"commodity": profit, "exploration": 0, "exobiology": 0, "purchase": 0}}
    return {"2026-10-02": {"Ekono": {"Rival Front": entry}}}


def test_hinder_is_a_task_type_needing_a_faction():
    assert "hinder" in TASK_TYPES
    assert validate_task_input("Ekono", "hinder", "", "", "") == "Enter the faction to hinder."
    assert validate_task_input("Ekono", "hinder", "Rival Front", "", "") == ""


def test_dropping_influence_and_missions_against_them():
    view = build_task_view(_task(), _report(weighted=-6), None, _hist(("2026-10-02", 0.10), ("2026-10-01", 0.12)),
                           None, LIMITS)
    assert view["status"] == STATUS_DROPPING
    assert "Your missions this tick: 6 INF against Rival Front" in view["lines"]
    assert "Influence 12.0% → 10.0% (as of 2026-10-02)" in view["lines"]
    assert view["guide"].startswith("Influence is zero-sum")


def test_warns_when_our_actions_help_them():
    view = build_task_view(_task(), _report(weighted=5, profit=1_000_000), None,
                           _hist(("2026-10-02", 0.12), ("2026-10-01", 0.11)), None, LIMITS)
    assert view["status"] == STATUS_TODO
    assert any("helped Rival Front by 5 INF" in w for w in view["warnings"])
    assert any("help them" in w for w in view["warnings"])


def test_hindering_our_own_faction_warns():
    view = build_task_view(_task(), {}, None, [], None, LIMITS, squadron_faction="rival front")
    assert any("squadron's own faction" in w for w in view["warnings"])


def test_retreat_countdown_is_aimed_at_pushing_them_out():
    hist = _hist(("2026-10-02", 0.02), ("2026-10-01", 0.022), active=("Retreat",))
    view = build_task_view(_task(), {}, None, hist, None, LIMITS, today=date(2026, 10, 2))
    assert any(line.startswith("Retreat active") for line in view["lines"])
    assert any("keep it there through the check day" in w for w in view["warnings"])
