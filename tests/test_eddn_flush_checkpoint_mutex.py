"""MainWindow._on_market_flush_tick() / _on_wal_checkpoint_tick() -- these
two independently-scheduled QTimers (45s vs 5min) previously had no
awareness of each other. Confirmed live: the EDDN flush's executemany()
write and a concurrent net.wal_checkpoint(TRUNCATE) landed on the same
file at the same moment, both exceeding the 30s busy_timeout -- one
throwing "database is locked" outright. Each tick must now also skip
while the OTHER worker is running, not just its own previous run."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _running_thread():
    return SimpleNamespace(isRunning=lambda: True)


def _idle_thread():
    return SimpleNamespace(isRunning=lambda: False)


def test_market_flush_tick_skips_while_wal_checkpoint_running():
    fake_self = SimpleNamespace(
        _flush_thread=None,
        _wal_checkpoint_thread=_running_thread(),
        eddn_market_cache=SimpleNamespace(pop_buffers=lambda: (_ for _ in ()).throw(
            AssertionError("should not pop buffers when skipping the tick"))),
    )
    MainWindow._on_market_flush_tick(fake_self)  # must return early, no AssertionError


def test_market_flush_tick_proceeds_when_wal_checkpoint_idle_and_nothing_buffered():
    empty = ()
    fake_self = SimpleNamespace(
        _flush_thread=None,
        _wal_checkpoint_thread=_idle_thread(),
        eddn_market_cache=SimpleNamespace(pop_buffers=lambda: (empty,) * 12),
    )
    # Reaches the "nothing buffered" early-return without constructing a worker.
    MainWindow._on_market_flush_tick(fake_self)


def test_wal_checkpoint_tick_skips_while_flush_running():
    calls = []
    fake_self = SimpleNamespace(
        _wal_checkpoint_thread=None,
        _flush_thread=_running_thread(),
    )
    MainWindow._on_wal_checkpoint_tick(fake_self)
    assert calls == []  # never reached worker construction (would need self.repo, absent here)


def test_wal_checkpoint_tick_skips_while_previous_checkpoint_running():
    fake_self = SimpleNamespace(
        _wal_checkpoint_thread=_running_thread(),
        _flush_thread=None,
    )
    MainWindow._on_wal_checkpoint_tick(fake_self)
