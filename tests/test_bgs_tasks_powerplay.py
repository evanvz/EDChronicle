"""BGS Tasks tracker: PowerPlay mode (reinforcement / acquisition /
undermining) worked out from the pledged power, merits earned in the task's
system this PowerPlay week, and a short "what to do" line on every card."""
from datetime import datetime, timezone
from types import SimpleNamespace

from edc.core.bgs_tasks import (
    DEFAULT_LIMITS, build_task_view, build_task_views, powerplay_mode, powerplay_week_start,
)

LIMITS = dict(DEFAULT_LIMITS)


def _task(task_type, faction=None, opponent=None, note=None, address=12345, task_id=1):
    return {"id": task_id, "system_address": address, "system_name": "Tucanae", "task_type": task_type,
            "faction_name": faction, "opponent_name": opponent, "note": note, "sort_order": 0,
            "created_at": "2026-09-26T00:00:00Z"}


def _act(action, bonus=(), merits="yes", bgs="safe"):
    return SimpleNamespace(action=action, bonus_powers=list(bonus), merits=merits, bgs=bgs)


class _Table:
    def __init__(self, acts):
        self.acts = acts
        self.calls = []

    def get_actions(self, system_type, pp_state=""):
        self.calls.append((system_type, pp_state))
        return self.acts


# --- PowerPlay week start (Thursday ~07:00 UTC, same estimate as the Faction Expansion Tracker) ---

def test_week_start_is_the_most_recent_thursday_0700_utc():
    # Saturday 2026-09-26 18:00 UTC -> Thursday 2026-09-24 07:00 UTC
    assert powerplay_week_start(datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)) == "2026-09-24T07:00:00Z"


def test_week_start_on_thursday_before_and_after_0700():
    assert powerplay_week_start(datetime(2026, 9, 24, 6, 59, tzinfo=timezone.utc)) == "2026-09-17T07:00:00Z"
    assert powerplay_week_start(datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)) == "2026-09-24T07:00:00Z"


# --- mode ---

def test_powerplay_mode_rules():
    assert powerplay_mode("Aisling Duval", "Aisling Duval", "Fortified") == "Reinforcement"
    assert powerplay_mode("Aisling Duval", "aisling duval", "Exploited") == "Reinforcement"
    assert powerplay_mode("Aisling Duval", "Zachary Hudson", "Stronghold") == "Undermining"
    assert powerplay_mode("Aisling Duval", "", "Unoccupied") == "Acquisition"
    assert powerplay_mode("Aisling Duval", "", "") == ""
    assert powerplay_mode("", "Zachary Hudson", "Stronghold") == ""


# --- PowerPlay card ---

_PP = {"pp_state": "Unoccupied", "pp_control_progress": 0.789, "pp_controlling_power": None,
       "pp_data_timestamp": "2026-09-26T10:00:00Z"}


def test_pledged_card_shows_mode_merits_and_top_activities_bonus_first():
    table = _Table([
        _act("Bounty Hunting"), _act("Power Kills"), _act("Suspended Thing", merits="suspended"),
        _act("Transport Powerplay Commodities", bonus=["Aisling Duval"]), _act("Holoscreen Hacking"),
        _act("Sell Rare Goods"),
    ])
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS,
                           pledged="Aisling Duval", merits=340, pp_activities=table)
    assert view["lines"][0] == "Acquisition: Unoccupied (no power yet) — 78.9%"
    assert "Your merits here this PowerPlay week: 340" in view["lines"]
    assert view["hud"] == "PowerPlay — Acquisition: Unoccupied (no power yet) — 78.9% · 340 merits this week"
    assert view["guide"] == ("Acquisition — BGS-safe: Transport Aisling Media Materials (collect at a Power "
                             "Contact in a supporting system in range (your Fortified within 20 ly / Stronghold "
                             "within 30 ly), deliver to the Power Contact here), "
                             "Bounty Hunting (cash vouchers elsewhere), Power Kills, Holoscreen Hacking")
    assert set(table.calls) == {("acquisition", "Unoccupied")}  # full + short guide both read it


def test_pledged_card_in_a_system_not_targetable():
    view = build_task_view(_task("powerplay"), {}, None, [],
                           dict(_PP, pp_state="", pp_control_progress=None), LIMITS,
                           pledged="Aisling Duval", merits=0, pp_activities=None)
    assert view["guide"] == "Not a PowerPlay target for your power right now"


def test_unpledged_card_says_to_pledge():
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS)
    assert view["guide"] == "Pledge to a power to see PowerPlay actions for this system"
    assert not any("merits" in line for line in view["lines"])


# --- guidance on the BGS cards ---

def test_boost_vote_fight_have_guidance_naming_the_factions():
    boost = build_task_view(_task("boost", "EUW"), {}, None, [], None, LIMITS)
    assert "EUW" in boost["guide"] and "25 INF+" in boost["guide"]
    vote = build_task_view(_task("vote", "A", "B"), {}, None, [], None, LIMITS)
    assert "Combat doesn't count" in vote["guide"]
    fight = build_task_view(_task("fight", "A", "B"), {}, None, [], None, LIMITS)
    assert "conflict zones for A" in fight["guide"] and "Don't cash bonds for B" in fight["guide"]
    note = build_task_view(_task("note", note="x"), {}, None, [], None, LIMITS)
    assert note["guide"] == ""


# --- builder fetches merits since the week start ---

def test_build_task_views_queries_merits_since_week_start():
    calls = []
    repo = SimpleNamespace(
        list_bgs_tasks=lambda: [_task("powerplay")],
        get_session_activity_report=lambda since: {},
        get_bgs_status_for_system=lambda addr: None,
        get_faction_history=lambda addr: [],
        get_system_powerplay_snapshot=lambda addr: _PP,
        get_powerplay_merits_since=lambda addr, since: calls.append((addr, since)) or 55,
        get_system_population=lambda addr: 51_900_000,
        get_held_systems_from_journal=lambda power: {},
        get_system_coords_for_names=lambda names: {},
    )
    now = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    views = build_task_views(repo, "t", LIMITS, pledged="Aisling Duval", now=now)
    assert calls == [(12345, "2026-09-24T07:00:00Z")]
    assert "Your merits here this PowerPlay week: 55" in views[0]["lines"]
    assert "Population: 51.9 million (large)" in views[0]["lines"]


def test_population_text():
    from edc.core.bgs_tasks import population_text
    assert population_text(51_900_000) == "51.9 million (large)"
    assert population_text(850_000) == "850k (small)"
    assert population_text(3_200_000_000) == "3.2 billion (large)"
    assert population_text(None) == "unknown"


# --- per-line target state on Boost cards ---

def _entry(count=0, weighted=0, bounties=0, exploration=0):
    return {
        "missions": {"count": count, "weighted": weighted, "primary_count": count, "secondary_count": 0,
                     "by_type": {}, "reward_total": 0, "reward_by_type": {}},
        "combat_bonds_total": 0, "bounties_total": bounties,
        "cz_kills": {"ground_l": 0, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 0},
        "trade_sold": {"commodity": 0, "exploration": exploration, "exobiology": 0},
    }


def test_boost_line_states_under_met_and_over():
    report = {"2026-09-26": {"Tucanae": {"EUW": _entry(count=5, weighted=25, bounties=21_000_000, exploration=1)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["line_states"][:3] == ["met", "over", ""]
    assert view["lines"][0] == "INF 25 / 25 (5 missions) ✓"
    assert view["lines"][1] == "Bounties 21.0M / 20.0M ✓"
    assert view["lines"][2] == "Exploration 1 / 20.0M"
    assert len(view["line_states"]) == len(view["lines"])


def test_non_boost_line_states_are_blank_and_aligned():
    view = build_task_view(_task("vote", "A", "B", note="x"), {}, None, [], None, LIMITS)
    assert view["line_states"] == [""] * len(view["lines"])


def test_single_mission_is_singular():
    report = {"2026-09-26": {"Tucanae": {"EUW": _entry(count=1, weighted=3)}}}
    view = build_task_view(_task("boost", "EUW"), report, None, [], None, LIMITS)
    assert view["lines"][0] == "INF 3 / 25 (1 mission)"


# --- BGS-safe first; joint BGS/PP actions only when also boosting ---

def test_guide_lists_bgs_safe_first_and_flags_joint_actions():
    table = _Table([_act("Sell for Large Profits", bonus=["Aisling Duval"], bgs="joint"),
                    _act("Scan Datalinks"), _act("Sell Rare Goods", bgs="joint")])
    view = build_task_view(_task("powerplay"), {}, None, [], _PP, LIMITS, pledged="Aisling Duval", pp_activities=table)
    assert view["guide"] == ("Acquisition — BGS-safe: Scan Datalinks. Only if also boosting the station's "
                             "faction: Sell for Large Profits, Sell Rare Goods")


# --- ZYADA allies: never Undermining ---

def test_allied_power_system_is_never_undermining():
    from edc.core.bgs_tasks import allied_powers
    allies = allied_powers("Aisling Duval")
    assert allies == {"zemina torval", "yuri grom", "a. lavigny-duval", "denton patreus"}
    # The game writes Arissa as "A. Lavigny-Duval"; both spellings must match.
    assert powerplay_mode("Aisling Duval", "A. Lavigny-Duval", "Fortified", allies=allies) == "Allied"
    assert powerplay_mode("Aisling Duval", "Denton Patreus", "Fortified", allies=allies) == "Allied"
    assert powerplay_mode("Aisling Duval", "Zachary Hudson", "Fortified", allies=allies) == "Undermining"


def test_allies_default_only_for_zyada_pledges_and_config_overrides():
    from edc.core.bgs_tasks import allied_powers
    assert allied_powers("Zachary Hudson") == frozenset()
    assert allied_powers("Aisling Duval", []) == frozenset()
    assert allied_powers("Aisling Duval", ["Li Yong-Rui", "Aisling Duval"]) == {"li yong-rui"}


def test_allied_card_says_do_not_undermine():
    pp = dict(_PP, pp_controlling_power="Arissa Lavigny-Duval", pp_state="Stronghold")
    view = build_task_view(_task("powerplay"), {}, None, [], pp, LIMITS, pledged="Aisling Duval")
    assert view["lines"][0].startswith("Allied:")
    assert view["guide"] == "Allied power's system — don't undermine it (coalition)"


# --- the commodity for the job ---

def test_transport_names_the_commodity_for_the_power_and_job():
    from edc.core.bgs_tasks import transport_text
    assert transport_text("Acquisition", "Aisling Duval").startswith("Transport Aisling Media Materials (")
    assert transport_text("Reinforcement", "Aisling Duval").startswith("Transport Aisling Sealed Contracts (")
    assert transport_text("Undermining", "Aisling Duval").startswith("Transport Aisling Programme Materials (")
    # the game writes Arissa as "A. Lavigny-Duval"; both spellings work
    assert "Lavigny Corruption Reports" in transport_text("Acquisition", "A. Lavigny-Duval")
    assert "Lavigny Corruption Reports" in transport_text("Acquisition", "Arissa Lavigny-Duval")
    assert transport_text("Acquisition", "Unknown Power") == "Transport Powerplay Commodities"


def test_commodity_lines_show_carrying_and_next_allocation():
    from edc.core.bgs_tasks import cargo_by_name, commodity_lines
    cargo = cargo_by_name([{"Name": "aislingmediamaterials", "Name_Localised": "Aisling Media Materials", "Count": 83},
                           {"Name": "drones", "Name_Localised": "Limpet", "Count": 4}])
    now = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)
    lines = commodity_lines("Acquisition", "Aisling Duval", cargo,
                            {"aisling media materials": "2026-10-02T20:53:19Z"}, now=now)
    assert lines[0].startswith("Commodity: Aisling Media Materials · carrying 83 t · next allocation ~")
    assert "30 min after your last collection" in lines[0]
    assert len(lines) == 1  # no generic merits claim any more
    with_history = commodity_lines("Acquisition", "Aisling Duval", cargo, None, now=now, last_delivery={
        "timestamp": "2026-10-02T22:11:03Z", "count": 83, "type": "Aisling Media Materials", "merits": 547})
    assert with_history[-1] == "Your last hand-in here: 83 t Aisling Media Materials → 547 merits (2026-10-02)"
    later = commodity_lines("Acquisition", "Aisling Duval", cargo,
                            {"aisling media materials": "2026-10-02T20:00:00Z"}, now=now)
    assert "allocation should be available again" in later[0]
    assert commodity_lines("Acquisition", "", None, None) == []


def test_collect_event_records_the_time(tmp_path):
    from edc.core.event_engine import EventEngine
    from edc.core.state import GameState
    eng = EventEngine(GameState(), tmp_path)
    state, _ = eng.process({"event": "PowerplayCollect", "timestamp": "2026-10-02T20:53:19Z", "Power": "Aisling Duval",
                            "Type": "aislingmediamaterials", "Type_Localised": "Aisling Media Materials", "Count": 83})
    assert state.pp_last_collect == {"aisling media materials": "2026-10-02T20:53:19Z"}



# --- Acquisition: commodities only count from a supporting system ---

def _support_fixture():
    from edc.core import bgs_tasks
    bgs_tasks._held_cache.clear()
    coords = {"Tucanae": (0.0, 0.0, 0.0), "HIP 114709": (28.1, 0.0, 0.0), "HIP 109203": (67.8, 0.0, 0.0),
              "Near Fort": (15.0, 0.0, 0.0), "Far Fort": (25.0, 0.0, 0.0)}
    repo = SimpleNamespace(
        get_held_systems_from_journal=lambda power: {"HIP 109203": ("Stronghold", "2026-10-02T20:45:33Z")},
        get_system_coords_for_names=lambda names: {n: coords[n] for n in names if n in coords},
    )
    edsm = SimpleNamespace(fetched_date="2026-10-02", held_systems=lambda power: {
        "HIP 114709": "Stronghold", "Near Fort": "Fortified", "Far Fort": "Fortified"})
    return repo, edsm


def test_supporting_systems_use_20ly_fortified_and_30ly_stronghold():
    from edc.core.bgs_tasks import supporting_systems
    repo, edsm = _support_fixture()
    found = supporting_systems(repo, "Aisling Duval", "Tucanae", edsm)
    assert [(n, s) for n, s, _d in found] == [("Near Fort", "Fortified"), ("HIP 114709", "Stronghold")]


def test_carried_goods_from_a_non_supporting_system_warn():
    from edc.core.bgs_tasks import commodity_lines, supporting_systems
    repo, edsm = _support_fixture()
    support = supporting_systems(repo, "Aisling Duval", "Tucanae", edsm)
    lines = commodity_lines("Acquisition", "Aisling Duval", {"aisling media materials": 83}, None,
                            supporting=support, collect_system={"aisling media materials": "HIP 109203"})
    assert "Collect at a supporting system: Near Fort (Fortified, 15.0 ly), HIP 114709 (Stronghold, 28.1 ly)" in lines
    assert any(l.startswith("⚠ Your 83 t were collected at HIP 109203") and "collect at Near Fort instead" in l
               for l in lines)
    ok = commodity_lines("Acquisition", "Aisling Duval", {"aisling media materials": 83}, None,
                         supporting=support, collect_system={"aisling media materials": "HIP 114709"})
    assert not any(l.startswith("⚠") for l in ok)



def test_one_hand_in_paid_in_several_merits_events_adds_up(tmp_path):
    from edc.core.event_engine import EventEngine
    from edc.core.state import GameState
    eng = EventEngine(GameState(), tmp_path)
    eng.state.system = "ICZ AG-O b6-5"
    eng.process({"event": "PowerplayDeliver", "timestamp": "2026-09-05T14:42:27Z", "Power": "Aisling Duval",
                 "Type_Localised": "Aisling Media Materials", "Count": 16})
    eng.process({"event": "PowerplayMerits", "timestamp": "2026-09-05T14:42:47Z", "MeritsGained": 105, "TotalMerits": 1})
    eng.process({"event": "PowerplayMerits", "timestamp": "2026-09-05T14:42:47Z", "MeritsGained": 3960, "TotalMerits": 2})
    eng.process({"event": "PowerplayMerits", "timestamp": "2026-09-05T14:50:00Z", "MeritsGained": 50, "TotalMerits": 3})
    assert eng.state.pp_deliveries["icz ag-o b6-5"]["merits"] == 4065


def test_delivery_history_scan_sums_merits_within_a_minute(tmp_path):
    import json
    from edc.core.powerplay_pledge_scanner import scan_deliveries
    events = [{"event": "FSDJump", "StarSystem": "ICZ AG-O b6-5", "timestamp": "2026-09-05T14:30:00Z"},
              {"event": "PowerplayDeliver", "timestamp": "2026-09-05T14:42:27Z", "Type_Localised": "Aisling Media Materials", "Count": 16},
              {"event": "PowerplayMerits", "timestamp": "2026-09-05T14:42:47Z", "MeritsGained": 105},
              {"event": "PowerplayMerits", "timestamp": "2026-09-05T14:42:47Z", "MeritsGained": 3960},
              {"event": "PowerplayMerits", "timestamp": "2026-09-05T15:10:00Z", "MeritsGained": 99}]
    (tmp_path / "Journal.2026-09-05T140000.01.log").write_text(chr(10).join(json.dumps(e) for e in events), encoding="utf-8")
    assert scan_deliveries(tmp_path)["icz ag-o b6-5"]["merits"] == 4065


# --- compact cards: bars + chips + short guide ---

def test_boost_card_has_bars_per_stream_and_influence_chip():
    report = {"2026-10-03": {"Tucanae": {"EUW": {"missions": {"count": 3, "weighted": 30}, "combat_bonds_total": 0,
              "bounties_total": 5_000_000, "cz_kills": {}, "trade_sold": {"commodity": 0, "exploration": 0,
                                                                             "exobiology": 0, "purchase": 0}}}}}
    task = dict(_task("boost"), faction_name="EUW", system_name="Tucanae")
    hist = [{"faction_name": "EUW", "snapshot_date": "2026-10-03", "influence": 0.43},
            {"faction_name": "EUW", "snapshot_date": "2026-10-02", "influence": 0.41}]
    view = build_task_view(task, report, None, hist, None, LIMITS)
    bars = {b["label"]: b for b in view["bars"]}
    assert bars["Missions"]["state"] == "over" and bars["Missions"]["text"] == "30 / 25 INF"
    assert bars["Bounties"]["value"] == 5_000_000 and bars["Bounties"]["state"] == ""
    assert view["chips"][0]["text"] == "Influence 43.0% ▲"
    assert view["guide_short"].startswith("Missions · bounties")


def test_powerplay_card_has_progress_bar_and_short_guide():
    table = _Table([_act("Transport Powerplay Commodities"), _act("Holoscreen Hacking"),
                    _act("Sell Rare Goods", bgs="joint")])
    pp = dict(_PP, pp_control_progress=None, pp_conflict_progress={"Aisling Duval": 0.835}, pp_powers=["Aisling Duval"])
    view = build_task_view(_task("powerplay"), {}, None, [], pp, LIMITS, pledged="Aisling Duval",
                           merits=554, pp_activities=table)
    assert view["bars"][0]["label"] == "Acquired" and view["bars"][0]["text"].startswith("83.5% — 16.5% to go")
    assert view["guide_short"] == "Transport Aisling Media Materials · Holoscreen Hacking"
    assert any(c["text"] == "554 merits this week" for c in view["chips"])


def test_rgba_helper_keeps_the_colour():
    from edc.ui.panels.bgs_tasks_dialog import _rgba
    assert _rgba("#FFB347", 0.7) == "rgba(255, 179, 71, 178)"
