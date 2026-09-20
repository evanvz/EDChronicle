"""_FactionRefreshWorker.run() (player_faction_panel.py) -- Phase 1C:
save_faction_snapshot() auto-commits internally, so saving N factions for
one system used to mean N commits. Now wrapped in one deferred_commit()
per system (not around the whole multi-minute refresh loop -- that loop's
own time.sleep(0.3)-per-system EDSM rate-limit would otherwise hold one
transaction open for the whole run, blocking every other writer for the
entire refresh). Real SQLite (tmp_path), a second raw connection observes
commit timing exactly like test_database_deferred_commit.py."""
import sqlite3
from unittest.mock import patch

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.ui.panels.player_faction_panel import _FactionRefreshWorker


def _seed_coords(db_path, system_name):
    db = Database(db_path)
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    db.conn.execute(
        "INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)",
        (system_name, 0.0, 0.0, 0.0),
    )
    db.conn.commit()
    db.close()


def test_factions_for_one_system_commit_together_not_per_faction(tmp_path):
    db_path = tmp_path / "edhelper.db"
    _seed_coords(db_path, "Sol")

    visibility_after_first_save = []

    def fake_fetch_system_factions(system_name):
        return {
            "system_address": 1,
            "system_name": "Sol",
            "factions": [
                {"Name": "Faction A", "Influence": 0.5, "is_controlling": True},
                {"Name": "Faction B", "Influence": 0.3, "is_controlling": False},
            ],
        }, None

    real_save = Repository.save_faction_snapshot
    call_count = []

    def spy_save(self, *args, **kwargs):
        real_save(self, *args, **kwargs)
        call_count.append(1)
        if len(call_count) == 1:
            other = sqlite3.connect(db_path)
            try:
                visibility_after_first_save.append(
                    other.execute("SELECT COUNT(*) FROM faction_snapshots").fetchone()[0]
                )
            finally:
                other.close()

    with patch(
        "edc.ui.panels.player_faction_panel.fetch_system_factions",
        side_effect=fake_fetch_system_factions,
    ), patch(
        "edc.ui.panels.player_faction_panel.derive_conflicts_from_factions_states",
        return_value=[],
    ), patch.object(Repository, "save_faction_snapshot", spy_save):
        worker = _FactionRefreshWorker(db_path, ["Sol"])
        worker.run()

    assert call_count == [1, 1]  # both factions actually saved
    # Neither faction was visible to another connection right after the
    # FIRST save -- proves the two saves share one deferred commit rather
    # than each committing immediately.
    assert visibility_after_first_save == [0]

    other = sqlite3.connect(db_path)
    try:
        assert other.execute("SELECT COUNT(*) FROM faction_snapshots").fetchone()[0] == 2
    finally:
        other.close()
