"""PowerPlay tasks: the squadron's stated mode (Reinforcement/Acquisition/
Undermining) or auto-detection, with EDSM filling in unvisited systems."""
from datetime import datetime, timezone
from types import SimpleNamespace

from edc.core.bgs_tasks import DEFAULT_LIMITS, build_task_view, describe_detection, detect_powerplay_mode
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

LIMITS = dict(DEFAULT_LIMITS)
_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _task(pp_mode=None):
    return {"id": 1, "system_address": None, "system_name": "Ekono", "task_type": "powerplay",
            "faction_name": None, "opponent_name": None, "note": None, "sort_order": 0,
            "created_at": "2026-10-01T00:00:00Z", "pp_mode": pp_mode}


def _act(action, bgs="safe"):
    return SimpleNamespace(action=action, bonus_powers=[], merits="yes", bgs=bgs)


class _Table:
    def get_actions(self, system_type, pp_state=""):
        return {"reinforcement": [_act("Scan Datalinks")], "undermining": [_act("Power Kills")],
                "acquisition": [_act("Holoscreen Hacking")]}[system_type]


def test_unvisited_system_uses_edsm_and_shows_its_guide():
    edsm = {"power": "Aisling Duval", "power_state": "Fortified", "date": _TODAY}
    view = build_task_view(_task(), {}, None, [], None, LIMITS, pledged="Aisling Duval",
                           pp_activities=_Table(), edsm_row=edsm)
    assert view["lines"][0] == "Reinforcement: Fortified, Aisling Duval (EDSM, 0 days old)"
    assert view["guide"].startswith("Reinforcement — BGS-safe: Scan Datalinks")


def test_edsm_acquisition_guess_is_flagged_range_unconfirmed():
    det = detect_powerplay_mode("Aisling Duval", None, {"power": "", "power_state": "Unoccupied", "date": _TODAY})
    assert det["mode"] == "Acquisition" and det["range_unconfirmed"]
    assert "range unconfirmed" in describe_detection(det)


def test_declared_mode_drives_the_guide_with_no_data_at_all():
    view = build_task_view(_task("Undermining"), {}, None, [], None, LIMITS, pledged="Aisling Duval",
                           pp_activities=_Table())
    assert view["lines"][0] == "Undermining (from your squadron's objective)"
    assert view["guide"].startswith("Undermining — BGS-safe: Power Kills")


def test_declared_mode_that_no_longer_matches_warns():
    edsm = {"power": "Zachary Hudson", "power_state": "Exploited", "date": _TODAY}
    view = build_task_view(_task("Reinforcement"), {}, None, [], None, LIMITS, pledged="Aisling Duval",
                           edsm_row=edsm)
    assert any("Task says Reinforcement" in w and "Zachary Hudson" in w for w in view["warnings"])


def test_undermining_an_allied_system_warns():
    edsm = {"power": "Denton Patreus", "power_state": "Stronghold", "date": _TODAY}
    view = build_task_view(_task("Undermining"), {}, None, [], None, LIMITS, pledged="Aisling Duval",
                           edsm_row=edsm)
    assert any("allied (ZYADA)" in w for w in view["warnings"])


def test_declared_acquisition_with_unconfirmed_range_does_not_warn():
    edsm = {"power": "", "power_state": "Unoccupied", "date": _TODAY}
    view = build_task_view(_task("Acquisition"), {}, None, [], None, LIMITS, pledged="Aisling Duval",
                           edsm_row=edsm)
    assert view["warnings"] == []


def test_pp_mode_is_saved_with_the_task(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.add_bgs_task("Ekono", "powerplay", pp_mode="Reinforcement")
    repo.add_bgs_task("Tucanae", "powerplay")
    assert [t["pp_mode"] for t in repo.list_bgs_tasks()] == ["Reinforcement", None]


def test_no_data_and_no_mode_asks_for_the_mode_instead_of_guessing():
    view = build_task_view(_task(), {}, None, [], None, LIMITS, pledged="Aisling Duval")
    assert view["guide"].startswith("No PowerPlay data for this system yet")
