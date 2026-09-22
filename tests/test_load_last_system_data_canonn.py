"""MainWindow.load_last_system_data() -- the one-shot startup loader that
fires QTimer.singleShot(0, win.load_last_system_data) in edc/app.py.
_maybe_start_ring_hotspot_check() was already wired in here (confirmed
via its own comment: ring data never loaded on startup without it), but
_maybe_start_canonn_refresh() wasn't -- confirmed live 2026-09-22 with
the game not even running: launching straight into a previously-visited
system never fetched Canonn's species/signal intel at all, since that
refresh was only ever triggered from the live Location/FSDJump handler.
Fake self, same pattern as test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345):
    calls = []
    return SimpleNamespace(
        system_data_loader=SimpleNamespace(
            load_last_system_data=lambda: calls.append("load_last_system_data")
        ),
        state=SimpleNamespace(system_address=system_address),
        _load_persisted_rings=lambda addr: calls.append(("_load_persisted_rings", addr)),
        _maybe_start_ring_hotspot_check=lambda: calls.append("_maybe_start_ring_hotspot_check"),
        _maybe_start_canonn_refresh=lambda: calls.append("_maybe_start_canonn_refresh"),
        _calls=calls,
    )


def test_startup_load_also_triggers_canonn_refresh():
    fake_self = _fake_self()
    MainWindow.load_last_system_data(fake_self)
    assert "_maybe_start_canonn_refresh" in fake_self._calls


def test_startup_load_still_triggers_ring_hotspot_check():
    fake_self = _fake_self()
    MainWindow.load_last_system_data(fake_self)
    assert "_maybe_start_ring_hotspot_check" in fake_self._calls


def test_no_system_address_skips_both_followups():
    fake_self = _fake_self(system_address=None)
    MainWindow.load_last_system_data(fake_self)
    assert "_maybe_start_canonn_refresh" not in fake_self._calls
    assert "_maybe_start_ring_hotspot_check" not in fake_self._calls
