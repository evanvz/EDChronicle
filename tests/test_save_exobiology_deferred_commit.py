"""MainWindow._save_exobiology_to_db() -- Phase 1C: save_exobiology()
auto-commits internally. DBSaved already bounds live play to 0-1 new
items per tick, but a bootstrap replay of historical journals can mature
several species to Complete in one call -- now wrapped in one
deferred_commit() for that burst case. Fake-self/SimpleNamespace pattern
already established for MainWindow method tests (see
test_bounty_if_candidates_cache.py), real Repository/Database (tmp_path)
since commit timing is what's under test, matching
test_database_deferred_commit.py's second-connection-observes-timing
pattern."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.ui.main_window import MainWindow


def _repo(tmp_path):
    db = Database(tmp_path / "edhelper.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return db, Repository(db)


def _exo_rec(body_name, genus, species, variant):
    return {
        "Complete": True, "DBSaved": False,
        "BodyName": body_name, "Genus": genus, "Species": species, "Variant": variant,
        "Samples": 3,
    }


def test_multiple_completed_species_commit_together(tmp_path):
    db, repo = _repo(tmp_path)
    fake_self = SimpleNamespace(
        state=SimpleNamespace(
            system_address=1,
            exo={
                "b1": _exo_rec("Body A", "Genus1", "Species1", "Variant1"),
                "b2": _exo_rec("Body B", "Genus2", "Species2", "Variant2"),
            },
        ),
        repo=repo,
    )

    visibility_after_first_save = []
    real_save = Repository.save_exobiology
    calls = []

    def spy_save(self, *args, **kwargs):
        real_save(self, *args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            other = sqlite3.connect(db.db_path)
            try:
                visibility_after_first_save.append(
                    other.execute("SELECT COUNT(*) FROM exobiology").fetchone()[0]
                )
            finally:
                other.close()

    with patch.object(Repository, "save_exobiology", spy_save):
        MainWindow._save_exobiology_to_db(fake_self)

    assert calls == [1, 1]
    assert visibility_after_first_save == [0]  # not committed until both are saved

    other = sqlite3.connect(db.db_path)
    try:
        assert other.execute("SELECT COUNT(*) FROM exobiology").fetchone()[0] == 2
    finally:
        other.close()

    assert fake_self.state.exo["b1"]["DBSaved"] is True
    assert fake_self.state.exo["b2"]["DBSaved"] is True
