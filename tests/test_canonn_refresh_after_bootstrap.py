"""The startup Canonn fetch runs before the journal replay has set the
commander name, so the nearest-challenge lookup failed with "No commander
name" on every launch and was never retried until the next system change.
It is re-run once the replay finishes."""
from unittest.mock import MagicMock

from edc.ui.main_window import MainWindow


def test_bootstrap_end_reruns_canonn_refresh():
    fake_self = MagicMock()
    fake_self._replaying = True
    MainWindow._on_event(fake_self, {"event": "_BootstrapEnd"})
    fake_self._maybe_start_canonn_refresh.assert_called_once_with()
