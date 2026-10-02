"""The pledge is recovered from journal history at startup: the login
"Powerplay" event comes before the last jump, so the startup replay misses it."""
import json

from edc.core.bgs_tasks import DEFAULT_LIMITS, build_task_view
from edc.core.powerplay_pledge_scanner import scan_powerplay_pledge


def _journal(tmp_path, name, events):
    (tmp_path / name).write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")


def test_latest_powerplay_event_gives_the_pledge(tmp_path):
    _journal(tmp_path, "Journal.2026-09-20T100000.01.log",
             [{"event": "Powerplay", "Power": "Zachary Hudson", "Rank": 5, "Merits": 10}])
    _journal(tmp_path, "Journal.2026-09-27T100000.01.log",
             [{"event": "LoadGame"}, {"event": "Powerplay", "Power": "Aisling Duval", "Rank": 173, "Merits": 1363352},
              {"event": "FSDJump"}, {"event": "PowerplayMerits", "Power": "Aisling Duval", "MeritsGained": 7}])
    assert scan_powerplay_pledge(tmp_path) == {"power": "Aisling Duval", "rank": 173, "merits": 1363352}


def test_leave_and_defect_and_nothing(tmp_path):
    assert scan_powerplay_pledge(tmp_path) is None
    _journal(tmp_path, "Journal.2026-09-27T100000.01.log",
             [{"event": "Powerplay", "Power": "Aisling Duval"}, {"event": "PowerplayLeave", "Power": "Aisling Duval"}])
    assert scan_powerplay_pledge(tmp_path)["power"] is None
    _journal(tmp_path, "Journal.2026-09-28T100000.01.log",
             [{"event": "PowerplayDefect", "FromPower": "Aisling Duval", "ToPower": "Zemina Torval"}])
    assert scan_powerplay_pledge(tmp_path)["power"] == "Zemina Torval"


def test_unpledged_card_does_not_claim_out_of_range():
    task = {"id": 1, "system_address": 1, "system_name": "Tucanae", "task_type": "powerplay", "faction_name": None,
            "opponent_name": None, "note": None, "sort_order": 0, "created_at": "x", "pp_mode": "Acquisition"}
    pp = {"pp_state": "Unoccupied", "pp_powers": ["Aisling Duval"], "pp_data_timestamp": "2026-09-26T21:51:42Z"}
    view = build_task_view(task, {}, None, [], pp, dict(DEFAULT_LIMITS), pledged="")
    assert view["warnings"] == []
    assert view["guide"] == "Pledge to a power to see PowerPlay actions for this system"
