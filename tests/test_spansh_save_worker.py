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

Both _on_spansh_enrichment and _on_spansh_saved defer their pending-retry
via QTimer.singleShot(0, ...) rather than calling _start_spansh_enrich()/
_start_spansh_save() directly -- confirmed live (2026-09-20) as a Qt
fatal crash ("QThread: Destroyed while thread '' is still running")
doing that synchronously: each of those two methods is the FIRST of two
slots connected to the same worker.finished signal (the second being the
old QThread's own .quit, still pending when the first slot runs), so
starting a brand-new QThread synchronously there races that old thread's
own not-yet-run shutdown slot. Tests patch QTimer.singleShot to invoke
the callback immediately (ignoring the delay) to keep these synchronous
and fast, matching what the next real event-loop tick would do anyway.
"""
import types
from types import SimpleNamespace
from unittest.mock import patch

from edc.ui.main_window import MainWindow, _SpanshSaveWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _immediate_single_shot(_delay_ms, callback):
    callback()


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


class _IdleThread:
    def isRunning(self):
        return False


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


@patch("edc.ui.main_window.QTimer.singleShot", side_effect=_immediate_single_shot)
def test_on_spansh_saved_drains_pending_when_still_current_system(_mock_shot):
    started = []
    merged = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123),
        system_data_loader=SimpleNamespace(
            merge_new_spansh_bodies=lambda addr: merged.append(addr)
        ),
        _spansh_save_pending=(123, [_body("Pending")]),
        _spansh_save_thread=None,
        _start_spansh_save=lambda addr, bodies: started.append((addr, [b["name"] for b in bodies])),
    )
    fake_self._retry_pending_spansh_save = types.MethodType(MainWindow._retry_pending_spansh_save, fake_self)
    MainWindow._on_spansh_saved(fake_self, 123)
    assert merged == [123]
    assert fake_self._spansh_save_pending is None
    assert started == [(123, ["Pending"])]


@patch("edc.ui.main_window.QTimer.singleShot", side_effect=_immediate_single_shot)
def test_on_spansh_saved_drops_pending_if_system_changed(_mock_shot):
    started = []
    merged = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=999),
        system_data_loader=SimpleNamespace(
            merge_new_spansh_bodies=lambda addr: merged.append(addr)
        ),
        _spansh_save_pending=(123, [_body("Stale")]),
        _spansh_save_thread=None,
        _start_spansh_save=lambda addr, bodies: started.append((addr, bodies)),
    )
    fake_self._retry_pending_spansh_save = types.MethodType(MainWindow._retry_pending_spansh_save, fake_self)
    MainWindow._on_spansh_saved(fake_self, 123)
    assert merged == []
    assert fake_self._spansh_save_pending is None
    assert started == []


def test_retry_pending_spansh_save_requeues_if_another_save_started_meanwhile():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=123),
        _spansh_save_thread=_BusyThread(),
        _spansh_save_pending=None,
        _start_spansh_save=lambda addr, bodies: started.append((addr, bodies)),
    )
    MainWindow._retry_pending_spansh_save(fake_self, 123, [_body("Requeued")])
    assert started == []
    assert fake_self._spansh_save_pending is not None


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


@patch("edc.ui.main_window.QTimer.singleShot", side_effect=_immediate_single_shot)
def test_on_spansh_enrichment_starts_pending_for_still_current_system(_mock_shot):
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=456),  # already jumped away from the just-finished system
        _spansh_save_thread=None,
        _spansh_save_pending=None,
        _start_spansh_save=lambda addr, bodies: None,
        _spansh_enrich_pending=("Wolf 359", 456),
        _enrich_thread=_IdleThread(),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    fake_self._retry_pending_spansh_enrich = types.MethodType(MainWindow._retry_pending_spansh_enrich, fake_self)
    MainWindow._on_spansh_enrichment(fake_self, [_body("Discarded")], "", 123)
    assert fake_self._spansh_enrich_pending is None
    assert started == [("Wolf 359", 456)]


@patch("edc.ui.main_window.QTimer.singleShot", side_effect=_immediate_single_shot)
def test_on_spansh_enrichment_drops_pending_if_jumped_again(_mock_shot):
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=999),  # jumped past B to a third system already
        _spansh_save_thread=None,
        _spansh_save_pending=None,
        _start_spansh_save=lambda addr, bodies: None,
        _spansh_enrich_pending=("Wolf 359", 456),
        _enrich_thread=_IdleThread(),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    fake_self._retry_pending_spansh_enrich = types.MethodType(MainWindow._retry_pending_spansh_enrich, fake_self)
    MainWindow._on_spansh_enrichment(fake_self, [_body("Discarded")], "", 123)
    assert fake_self._spansh_enrich_pending is None
    assert started == []


def test_retry_pending_spansh_enrich_skips_if_another_enrich_already_running():
    # Regression for the live crash: if a different enrich already
    # started in the interim (e.g. a fresh arrival re-triggered the
    # check before this deferred retry ran), must not start a second one
    # on top of it.
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=456),
        _enrich_thread=_BusyEnrichThread(),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    MainWindow._retry_pending_spansh_enrich(fake_self, "Wolf 359", 456)
    assert started == []


def test_retry_pending_spansh_enrich_starts_when_thread_free():
    started = []
    fake_self = SimpleNamespace(
        state=SimpleNamespace(system_address=456),
        _enrich_thread=_IdleThread(),
        _start_spansh_enrich=lambda name, addr: started.append((name, addr)),
    )
    MainWindow._retry_pending_spansh_enrich(fake_self, "Wolf 359", 456)
    assert started == [("Wolf 359", 456)]
