"""bgs_tasks table + Repository CRUD for the BGS Tasks tracker. Real
SQLite (temp file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_system(repo, system_address, system_name):
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (?, ?)", (system_address, system_name))


def test_resolve_system_is_case_insensitive_and_returns_canonical_name(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    assert repo.resolve_system("ekono") == (12345, "Ekono")
    assert repo.resolve_system("  EKONO ") == (12345, "Ekono")


def test_resolve_system_falls_back_to_eddn_bgs_status(tmp_path):
    repo = _repo(tmp_path)
    repo.db.execute(
        "INSERT INTO net.system_bgs_status (system_address, system_name, conflicts, faction_states, data_timestamp, source) "
        "VALUES (777, 'Kanuket', '[]', '[]', '2026-09-26T00:00:00Z', 'eddn')"
    )
    assert repo.resolve_system("kanuket") == (777, "Kanuket")


def test_resolve_system_unknown_or_blank_is_none(tmp_path):
    repo = _repo(tmp_path)
    assert repo.resolve_system("Nowhere") is None
    assert repo.resolve_system("") is None


def test_add_and_list_tasks_in_entry_order(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    first = repo.add_bgs_task("ekono", "boost", faction_name="Elite United Worlds")
    second = repo.add_bgs_task("Kanuket", "vote", faction_name="Remnants of the Code", opponent_name="Elite United Worlds")
    tasks = repo.list_bgs_tasks()
    assert [t["id"] for t in tasks] == [first, second]
    assert tasks[0]["system_address"] == 12345
    assert tasks[0]["system_name"] == "Ekono"
    assert tasks[0]["task_type"] == "boost"
    assert tasks[0]["opponent_name"] is None
    assert tasks[1]["system_address"] is None  # not seen yet
    assert tasks[1]["system_name"] == "Kanuket"
    assert tasks[1]["opponent_name"] == "Elite United Worlds"
    assert len(tasks[0]["created_at"]) == 20 and tasks[0]["created_at"].endswith("Z")


def test_list_resolves_a_system_seen_after_the_task_was_added(tmp_path):
    repo = _repo(tmp_path)
    repo.add_bgs_task("kanuket", "vote", faction_name="A", opponent_name="B")
    _seed_system(repo, 777, "Kanuket")
    tasks = repo.list_bgs_tasks()
    assert tasks[0]["system_address"] == 777
    assert tasks[0]["system_name"] == "Kanuket"
    row = repo.db.conn.execute("SELECT system_address FROM bgs_tasks").fetchone()
    assert row["system_address"] == 777  # persisted, not just returned


def test_delete_task(tmp_path):
    repo = _repo(tmp_path)
    task_id = repo.add_bgs_task("Ekono", "note", note="check in")
    repo.delete_bgs_task(task_id)
    assert repo.list_bgs_tasks() == []


def test_move_task_up_and_down(tmp_path):
    repo = _repo(tmp_path)
    a = repo.add_bgs_task("A", "note", note="a")
    b = repo.add_bgs_task("B", "note", note="b")
    c = repo.add_bgs_task("C", "note", note="c")
    repo.move_bgs_task(c, -1)
    assert [t["id"] for t in repo.list_bgs_tasks()] == [a, c, b]
    repo.move_bgs_task(a, +1)
    assert [t["id"] for t in repo.list_bgs_tasks()] == [c, a, b]
    repo.move_bgs_task(c, -1)  # already first -- no-op
    assert [t["id"] for t in repo.list_bgs_tasks()] == [c, a, b]


def test_known_names(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 2, "Kanuket")
    _seed_system(repo, 1, "Ekono")
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Hungarian Wolves', '2026-09-25')"
    )
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Elite United Worlds', '2026-09-25')"
    )
    repo.db.execute(
        "INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date) VALUES (1, 'Elite United Worlds', '2026-09-26')"
    )
    assert repo.get_known_system_names() == ["Ekono", "Kanuket"]
    assert repo.get_known_faction_names(1) == ["Elite United Worlds", "Hungarian Wolves"]
