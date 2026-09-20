"""MainWindow._SpanshSaveWorker -- moves the Spansh body-save loop off the
UI thread. Previously ran synchronously in _on_spansh_enrichment (a
finished-slot callback on the UI thread), each save auto-committing via
Database.execute() -- confirmed live as the freeze reported 2026-08-27
for systems Spansh returns hundreds of bodies for. The actual "one
commit, not one per body" behavior is Database.deferred_commit()'s own
job, already covered by tests/test_database_deferred_commit.py -- this
just confirms the worker wires it correctly end to end. Real temp-file
Database/Repository, same fixture pattern as
tests/test_eddn_market_bgs_res_buffering.py.

Overlapping enrichment while a save is running uses a one-slot last-wins
pending queue (_spansh_save_pending) instead of dropping the payload.
"""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow, _SpanshSaveWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _body(name, planet_class="Icy body"):
    return {"name": name, "planet_class": planet_class, "distance_ls": 100.0}


def test_saves_all_bodies_and_emits_system_address(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    worker = _SpanshSaveWorker(db_path, 123, [_body("Body A"), _body("Body B")])
    results = []
    worker.finished.connect(lambda addr: results.append(addr))
    worker.run()

    assert results == [123]
    db = Database(db_path)
    try:
        rows = Repository(db).get_spansh_bodies(123)
        assert {r["body_name"] for r in rows} == {"Body A", "Body B"}
    finally:
        db.close()


def test_empty_bodies_list_emits_and_saves_nothing(tmp_path):
    db_path = tmp_path / "test.db"
    setup_db = Database(db_path)
    setup_db.executescript(SCHEMA_SQL)
    setup_db.run_migrations()
    setup_db.close()

    worker = _SpanshSaveWorker(db_path, 123, [])
    results = []
    worker.finished.connect(lambda addr: results.append(addr))
    worker.run()

    assert results == [123]
    db = Database(db_path)
    try:
        assert Repository(db).get_spansh_bodies(123) == []
    finally:
        db.close()


class _BusyThread:
    def isRunning(self):
        return True


def test_enrichment_while_save_running_stashes_pending_last_wins():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123),
        repo=SimpleNamespace(db=SimpleNamespace(db_path="unused.db")),
        _spansh_save_thread=_BusyThread(),
        _spansh_save_pending=None,
        _spansh_enrich_pending=None,
        _start_spansh_save=lambda addr, bodies: started.append((addr, bodies)),
    )
    bodies_a = [_body("A")]
    bodies_b = [_body("B")]
    MainWindow._on_spansh_enrichment(fake_self, bodies_a, "", 123)
    MainWindow._on_spansh_enrichment(fake_self, bodies_b, "", 123)
    assert started == []
    assert fake_self._spansh_save_pending == (123, bodies_b)


def test_on_spansh_saved_drains_pending_when_still_current_system():
    started = []
    merged = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123),
        system_data_loader=SimpleNamespace(
            merge_new_spansh_bodies=lambda addr: merged.append(addr)
        ),
        _spansh_save_pending=(123, [_body("Pending")]),
        _start_spansh_save=lambda addr, bodies: started.append((addr, [b["name"] for b in bodies])),
    )
    MainWindow._on_spansh_saved(fake_self, 123)
    assert merged == [123]
    assert fake_self._spansh_save_pending is None
    assert started == [(123, ["Pending"])]


def test_on_spansh_saved_drops_pending_if_system_changed():
    started = []
    merged = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=999),
        system_data_loader=SimpleNamespace(
            merge_new_spansh_bodies=lambda addr: merged.append(addr)
        ),
        _spansh_save_pending=(123, [_body("Stale")]),
        _start_spansh_save=lambda addr, bodies: started.append((addr, bodies)),
    )
    MainWindow._on_spansh_saved(fake_self, 123)
    assert merged == []
    assert fake_self._spansh_save_pending is None
    assert started == []


# --- Enrich (fetch) step's own last-wins queue, _spansh_enrich_pending ---
#
# Confirmed live (2026-09-20): a rapid A->B jump inside the ~3s Spansh
# round-trip previously dropped B's fetch entirely (the busy-thread guard
# in _maybe_start_spansh_enrichment returned with nothing queued) and
# threw away A's completed-but-now-irrelevant result in
# _on_spansh_enrichment. Not a freeze/crash -- self-heals on a later
# revisit -- but wastes an API call and leaves B Spansh-blank until then.


class _BusyEnrichThread:
    def isRunning(self):
        return True


def test_enrichment_check_while_enrich_running_stashes_pending_last_wins():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system="Sol", system_address=123),
        repo=SimpleNamespace(
            count_real_bodies=lambda addr: 0,
            count_spansh_bodies=lambda addr: 0,
        ),
        _enrich_thread=_BusyEnrichThread(),
        _spansh_enrich_pending=None,
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    MainWindow._maybe_start_spansh_enrichment(fake_self)
    assert started == []
    assert fake_self._spansh_enrich_pending == ("Sol", 123)


def test_on_spansh_enrichment_starts_pending_for_still_current_system():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=456),  # already jumped away from the just-finished system
        _spansh_save_thread=None,
        _spansh_save_pending=None,
        _start_spansh_save=lambda addr, bodies: None,
        _spansh_enrich_pending=("Wolf 359", 456),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    MainWindow._on_spansh_enrichment(fake_self, [_body("Discarded")], "", 123)
    assert fake_self._spansh_enrich_pending is None
    assert started == [("Wolf 359", 456)]


def test_on_spansh_enrichment_drops_pending_if_jumped_again():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=999),  # jumped past B to a third system already
        _spansh_save_thread=None,
        _spansh_save_pending=None,
        _start_spansh_save=lambda addr, bodies: None,
        _spansh_enrich_pending=("Wolf 359", 456),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    MainWindow._on_spansh_enrichment(fake_self, [_body("Discarded")], "", 123)
    assert fake_self._spansh_enrich_pending is None
    assert started == []
