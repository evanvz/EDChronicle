"""UI-thread freezes found in the 2026-10-01 overnight log: the EDDN
PowerPlay cache save and the Player Faction overview query now run off
the UI thread."""
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from edc.core.eddn_powerplay import EddnPowerPlayCache

_app = QApplication.instance() or QApplication(sys.argv)


def test_cache_save_on_a_thread_while_ingesting_does_not_break(tmp_path):
    # Background saves while the main thread keeps ingesting must leave a
    # valid, loadable file. (The cache's lock mainly serialises overlapping
    # writers, e.g. the shutdown save racing a background save.)
    cache = EddnPowerPlayCache(tmp_path)
    for i in range(20000):
        cache.ingest(i, "Aisling Duval", "Fortified", "2026-10-01T00:00:00Z")
    errors = []

    def saver():
        try:
            for _ in range(5):
                cache.save()
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=saver)
    t.start()
    i = 20000
    while t.is_alive():
        cache.ingest(i, "Zachary Hudson", "Exploited", "2026-10-01T00:00:01Z")
        i += 1
    t.join()
    assert errors == []
    assert EddnPowerPlayCache(tmp_path).system_count() > 20000


def test_overview_refresh_coalesces_without_deadlock(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    from edc.ui.panels.player_faction_panel import PlayerFactionPanel

    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    panel = PlayerFactionPanel(Repository(db))
    panel.refresh(None)
    panel.refresh(None)  # while the first load runs -> one more load afterwards
    deadline = time.monotonic() + 10
    while (panel._overview_thread.isRunning() or panel._overview_reload_pending) and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.01)
    _app.processEvents()
    assert not panel._overview_thread.isRunning()
    assert "not currently aligned" in panel._summary_label.text()
