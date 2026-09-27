"""Repository.save_system_powerplay_snapshot / get_system_powerplay_snapshot
-- persists the journal's own live PowerplayState* reading (only ever
present on Location/FSDJump), previously held only in memory and lost
the instant the player left the system. Deliberately a separate concern
from FdevPowerPlayCache's CSV feed, which measures a different weekly
control-vote pool. Real SQLite (temp file), matching this repo's
convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_returns_none_when_never_visited(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_system_powerplay_snapshot(12345) is None


def test_saves_and_reads_back_a_snapshot(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_powerplay_snapshot(
        system_address=12345, system_name="Ekono", pp_state="Stronghold",
        control_progress=0.268642, reinforcement=908, undermining=4666,
        controlling_power="Aisling Duval", powers=["Aisling Duval"],
        data_timestamp="2026-09-24T21:34:20Z",
    )
    snap = repo.get_system_powerplay_snapshot(12345)
    assert snap == {
        "pp_state": "Stronghold", "pp_control_progress": 0.268642,
        "pp_reinforcement": 908, "pp_undermining": 4666,
        "pp_controlling_power": "Aisling Duval", "pp_powers": ["Aisling Duval"],
        "pp_data_timestamp": "2026-09-24T21:34:20Z", "pp_conflict_progress": {},
    }


def test_a_later_visit_overwrites_the_earlier_reading(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_powerplay_snapshot(
        system_address=12345, system_name="Ekono", pp_state="Stronghold",
        control_progress=0.268408, reinforcement=674, undermining=4666,
        controlling_power="Aisling Duval", powers=["Aisling Duval"],
        data_timestamp="2026-09-24T16:21:02Z",
    )
    repo.save_system_powerplay_snapshot(
        system_address=12345, system_name="Ekono", pp_state="Stronghold",
        control_progress=0.268642, reinforcement=908, undermining=4666,
        controlling_power="Aisling Duval", powers=["Aisling Duval"],
        data_timestamp="2026-09-24T21:34:20Z",
    )
    snap = repo.get_system_powerplay_snapshot(12345)
    assert snap["pp_reinforcement"] == 908
    assert snap["pp_data_timestamp"] == "2026-09-24T21:34:20Z"


def test_works_when_no_prior_systems_row_exists(tmp_path):
    """save_faction_snapshot()/save_system_name_if_missing() normally
    creates the systems row first -- this confirms the PowerPlay snapshot
    doesn't depend on that having already happened."""
    repo = _repo(tmp_path)
    repo.save_system_powerplay_snapshot(
        system_address=999, system_name="Aiga", pp_state="Exploited",
        control_progress=0.187426, reinforcement=0, undermining=0,
        controlling_power="Aisling Duval", powers=["Aisling Duval"],
        data_timestamp="2026-09-24T16:21:06Z",
    )
    snap = repo.get_system_powerplay_snapshot(999)
    assert snap["pp_state"] == "Exploited"


def test_empty_powers_list_round_trips_as_empty_list(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_powerplay_snapshot(
        system_address=12345, system_name="Ekono", pp_state="Unoccupied",
        control_progress=None, reinforcement=None, undermining=None,
        controlling_power=None, powers=[],
        data_timestamp="2026-09-24T16:21:02Z",
    )
    snap = repo.get_system_powerplay_snapshot(12345)
    assert snap["pp_powers"] == []
