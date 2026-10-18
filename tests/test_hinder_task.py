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


def test_hinder_card_has_an_influence_bar():
    view = build_task_view(_task(), _report(weighted=-6), None, _hist(("2026-10-02", 0.10), ("2026-10-01", 0.12)),
                           None, LIMITS)
    bar = view["bars"][0]
    assert bar["label"] == "Their influence" and bar["text"] == "10.0% ▼  (was 12.0%)" and bar["state"] == "met"
    assert view["chips"][0]["text"] == "Your missions −6 INF"


# --- 2026-10-18: hitting a faction through the stations it owns ---

def _hit_report(loss=0, smuggled=0, failed=0, bought=0):
    entry = {"missions": {"count": 0, "weighted": 0}, "combat_bonds_total": 0, "bounties_total": 0, "cz_kills": {},
             "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0, "purchase": bought,
                            "loss": loss, "smuggling": smuggled, "mission_failed": failed}}
    return {"2026-10-18": {"Ekono": {"Rival Front": entry}}}


def test_card_lists_their_stations_and_counts_loss_smuggling_and_failed_missions():
    stations = [{"station_name": "Rival Dock", "pad_size": "L", "has_market": True, "has_black_market": True},
                {"station_name": "Rival Camp", "pad_size": "M", "has_market": False, "has_black_market": False}]
    view = build_task_view(_task(), _hit_report(loss=1_200_000, smuggled=64, failed=2), None,
                           _hist(("2026-10-18", 0.10)), None, LIMITS, faction_stations=stations)
    assert "Their stations here: Rival Dock (L pad · market · black market), Rival Camp (M pad)" in view["lines"]
    assert [c["text"] for c in view["chips"]] == ["Sold at a loss −1.2M", "Smuggled 64t", "2 failed missions"]


def test_no_stations_known_and_buying_warns():
    view = build_task_view(_task(), _hit_report(bought=500_000), None, [], None, LIMITS, faction_stations=[])
    assert any(l.startswith("No Rival Front stations known here") for l in view["lines"])
    assert any("Buying at Rival Front stations" in w for w in view["warnings"])


def test_abandoned_missions_shown_as_unverified():
    entry = {"missions": {"count": 0, "weighted": 0}, "combat_bonds_total": 0, "bounties_total": 0, "cz_kills": {},
             "trade_sold": {"commodity": 0, "exploration": 0, "exobiology": 0, "purchase": 0, "loss": 0,
                            "smuggling": 0, "mission_failed": 0, "mission_abandoned": 5}}
    view = build_task_view(_task(), {"2026-10-18": {"Ekono": {"Rival Front": entry}}}, None, [], None, LIMITS)
    chip = view["chips"][0]
    assert chip["text"] == "5 abandoned (effect unverified)" and "expire" in chip["tooltip"]
