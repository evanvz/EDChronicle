from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_plan_round_trip(tmp_path):
    r = _repo(tmp_path)
    r.save_colonisation_plan_step(1, "A 1", "orbital", 0, "Coriolis", "Planned")
    r.save_colonisation_plan_step(1, "A 1", "surface", 1, "Outpost", "Building", 42)
    r.save_colonisation_plan_settings(1, "Industrial", True, "A 1")
    plan = r.get_colonisation_plan(1)
    assert plan["settings"] == {"kind": "Industrial", "group": True, "primary_body": "A 1"}
    assert len(plan["steps"]) == 2
    assert {"facility": "Outpost", "body": "A 1", "location": "surface",
            "slot_index": 1, "status": "Building", "market_id": 42} in plan["steps"]


def test_upsert_replaces_same_slot(tmp_path):
    r = _repo(tmp_path)
    r.save_colonisation_plan_step(1, "A 1", "orbital", 0, "Coriolis", "Planned")
    r.save_colonisation_plan_step(1, "A 1", "orbital", 0, "Outpost", "Built")
    steps = r.get_colonisation_plan(1)["steps"]
    assert len(steps) == 1 and steps[0]["facility"] == "Outpost" and steps[0]["status"] == "Built"
    r.save_colonisation_plan_settings(1, None, False, None)
    r.save_colonisation_plan_settings(1, "Tourism", True, "B")
    assert r.get_colonisation_plan(1)["settings"]["kind"] == "Tourism"


def test_delete_removes_only_that_slot(tmp_path):
    r = _repo(tmp_path)
    r.save_colonisation_plan_step(1, "A 1", "orbital", 0, "Coriolis", "Planned")
    r.save_colonisation_plan_step(1, "A 1", "orbital", 1, "Outpost", "Planned")
    r.delete_colonisation_plan_step(1, "A 1", "orbital", 0)
    steps = r.get_colonisation_plan(1)["steps"]
    assert [s["slot_index"] for s in steps] == [1]


def test_other_system_isolated(tmp_path):
    r = _repo(tmp_path)
    r.save_colonisation_plan_step(1, "A 1", "orbital", 0, "Coriolis", "Planned")
    r.save_colonisation_plan_settings(1, "Industrial", False, None)
    assert r.get_colonisation_plan(2) == {"settings": None, "steps": []}


def test_empty_system_returns_none_settings_and_no_steps(tmp_path):
    assert _repo(tmp_path).get_colonisation_plan(9) == {"settings": None, "steps": []}
