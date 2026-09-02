"""Repository.save_body_mining_signal()/get_spansh_bodies() -- crowd-sourced
surface_mining_signals column on net.spansh_bodies (Surface Mining, Update
4.4). save_body_mining_signal() must only ever touch this one column, never
clobbering planet_class/distance_ls/estimated_value/landable already cached
there by a fuller Spansh save_spansh_body() row -- see the method's
docstring for why save_spansh_body() itself can't be reused here."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_save_body_mining_signal_inserts_minimal_row(tmp_path):
    repo = _repo(tmp_path)
    repo.save_body_mining_signal(1281804437875, "HR 8769 A 1", 6)

    rows = repo.get_spansh_bodies(1281804437875)
    assert len(rows) == 1
    assert rows[0]["body_name"] == "HR 8769 A 1"
    assert rows[0]["surface_mining_signals"] == 6


def test_save_body_mining_signal_does_not_clobber_existing_spansh_row(tmp_path):
    repo = _repo(tmp_path)
    repo.save_spansh_body(
        system_address=1281804437875, body_name="HR 8769 A 1",
        planet_class="High metal content body", distance_ls=357.2,
        estimated_value=12345, landable=1,
    )

    repo.save_body_mining_signal(1281804437875, "HR 8769 A 1", 6)

    rows = repo.get_spansh_bodies(1281804437875)
    assert len(rows) == 1
    assert rows[0]["planet_class"] == "High metal content body"
    assert rows[0]["distance_ls"] == 357.2
    assert rows[0]["estimated_value"] == 12345
    assert rows[0]["surface_mining_signals"] == 6


def test_save_body_mining_signal_overwrites_previous_count(tmp_path):
    repo = _repo(tmp_path)
    repo.save_body_mining_signal(1, "Body 1", 3)
    repo.save_body_mining_signal(1, "Body 1", 6)

    rows = repo.get_spansh_bodies(1)
    assert rows[0]["surface_mining_signals"] == 6
