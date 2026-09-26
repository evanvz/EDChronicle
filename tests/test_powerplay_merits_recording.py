"""PowerplayMerits journal events are recorded against the system the player
is in, for the BGS Tasks tracker's per-system "merits this PowerPlay week"."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.ui.main_window import MainWindow
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_merits_summed_per_system_since(tmp_path):
    repo = _repo(tmp_path)
    repo.record_powerplay_merits(1, "Aisling Duval", 7, "2026-09-23T10:00:00Z")   # previous week
    repo.record_powerplay_merits(1, "Aisling Duval", 7, "2026-09-26T14:24:19Z")
    repo.record_powerplay_merits(1, "Aisling Duval", 40, "2026-09-26T14:28:17Z")
    repo.record_powerplay_merits(2, "Aisling Duval", 99, "2026-09-26T14:30:00Z")  # other system
    assert repo.get_powerplay_merits_since(1, "2026-09-24T07:00:00Z") == 47
    assert repo.get_powerplay_merits_since(3, "2026-09-24T07:00:00Z") == 0


def test_event_is_recorded_for_current_system():
    saved = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=560249932147),
        repo=SimpleNamespace(record_powerplay_merits=lambda *a: saved.append(a)),
    )
    evt = {"event": "PowerplayMerits", "Power": "Aisling Duval", "MeritsGained": 7,
           "TotalMerits": 1357123, "timestamp": "2026-09-26T14:24:19Z"}
    MainWindow._record_powerplay_merits(fake_self, evt)
    assert saved == [(560249932147, "Aisling Duval", 7, "2026-09-26T14:24:19Z")]


def test_event_skipped_without_system_or_merits():
    saved = []
    fake_self = SimpleNamespace(state=SimpleNamespace(system_address=None),
                                repo=SimpleNamespace(record_powerplay_merits=lambda *a: saved.append(a)))
    MainWindow._record_powerplay_merits(fake_self, {"event": "PowerplayMerits", "MeritsGained": 7})
    fake_self.state.system_address = 1
    MainWindow._record_powerplay_merits(fake_self, {"event": "PowerplayMerits", "MeritsGained": 0})
    assert saved == []


def _dispatch_fake_self(replaying):
    fake_self = MagicMock()
    fake_self._replaying = replaying
    fake_self.engine.process.return_value = (MagicMock(), [])
    fake_self.cfg.eddn_contribute_enabled = False
    return fake_self


def test_dispatch_skipped_during_replay_and_fires_live():
    evt = {"event": "PowerplayMerits", "Power": "Aisling Duval", "MeritsGained": 7, "timestamp": "2026-09-26T14:24:19Z"}
    replay = _dispatch_fake_self(True)
    MainWindow._on_event(replay, evt)
    replay._record_powerplay_merits.assert_not_called()
    live = _dispatch_fake_self(False)
    MainWindow._on_event(live, evt)
    live._record_powerplay_merits.assert_called_once_with(evt)
    live._notify_bgs_activity.assert_called_once_with()
