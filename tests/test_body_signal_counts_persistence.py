"""Repository.save_body_signal_counts()/get_spansh_bodies() -- crowd-sourced
bio/geo/human/guardian/thargoid/mining signal columns on net.spansh_bodies
(generalized from mining-only, Surface Mining's original motivation).
save_body_signal_counts() must only ever touch the columns it's given a
value for (COALESCE), never clobbering an unrelated signal type set by a
previous call, and never clobbering planet_class/distance_ls/
estimated_value/landable already cached by a fuller Spansh
save_spansh_body() row -- see the method's docstring for why
save_spansh_body() itself can't be reused here."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_save_body_signal_counts_inserts_minimal_row(tmp_path):
    repo = _repo(tmp_path)
    repo.save_body_signal_counts(1281804437875, "HR 8769 A 1", mining=6, geo=3)

    rows = repo.get_spansh_bodies(1281804437875)
    assert len(rows) == 1
    assert rows[0]["body_name"] == "HR 8769 A 1"
    assert rows[0]["surface_mining_signals"] == 6
    assert rows[0]["geo_signals"] == 3


def test_save_body_signal_counts_does_not_clobber_existing_spansh_row(tmp_path):
    repo = _repo(tmp_path)
    repo.save_spansh_body(
        system_address=1281804437875, body_name="HR 8769 A 1",
        planet_class="High metal content body", distance_ls=357.2,
        estimated_value=12345, landable=1,
    )

    repo.save_body_signal_counts(1281804437875, "HR 8769 A 1", mining=6)

    rows = repo.get_spansh_bodies(1281804437875)
    assert len(rows) == 1
    assert rows[0]["planet_class"] == "High metal content body"
    assert rows[0]["distance_ls"] == 357.2
    assert rows[0]["estimated_value"] == 12345
    assert rows[0]["surface_mining_signals"] == 6


def test_save_body_signal_counts_overwrites_previous_count(tmp_path):
    repo = _repo(tmp_path)
    repo.save_body_signal_counts(1, "Body 1", mining=3)
    repo.save_body_signal_counts(1, "Body 1", mining=6)

    rows = repo.get_spansh_bodies(1)
    assert rows[0]["surface_mining_signals"] == 6


def test_save_body_signal_counts_does_not_clobber_other_signal_types(tmp_path):
    # A message with only "mining" must not null out a "bio" count a
    # previous message already stored, and vice versa.
    repo = _repo(tmp_path)
    repo.save_body_signal_counts(1, "Body 1", bio=4)
    repo.save_body_signal_counts(1, "Body 1", mining=6)

    rows = repo.get_spansh_bodies(1)
    assert rows[0]["bio_signals"] == 4
    assert rows[0]["surface_mining_signals"] == 6


def test_save_body_signal_counts_stores_all_six_buckets(tmp_path):
    repo = _repo(tmp_path)
    repo.save_body_signal_counts(
        1, "Body 1", bio=4, geo=3, human=1, guardian=2, thargoid=5, mining=6,
    )

    rows = repo.get_spansh_bodies(1)
    assert rows[0]["bio_signals"] == 4
    assert rows[0]["geo_signals"] == 3
    assert rows[0]["human_signals"] == 1
    assert rows[0]["guardian_signals"] == 2
    assert rows[0]["thargoid_signals"] == 5
    assert rows[0]["surface_mining_signals"] == 6
