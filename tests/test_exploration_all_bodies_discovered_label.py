"""ExplorationPanel._refresh_signals() -- the "All N bodies discovered"
label used to key off state.fss_complete (FSSDiscoveryScan Progress>=1.0,
i.e. the spectrum sweep found every non-body signal source), not off
actually having scanned every body. Confirmed live: HIP 92742, honk
completed (fss_complete=True) with zero Scan events for any of its 3
bodies -- only the arrival star counted as resolved -- still showed
"All 3 bodies discovered" in green. Must compare resolved count against
total instead."""
from types import SimpleNamespace

from edc.ui.panels.exploration_panel import ExplorationPanel


class _FakeLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


def _fake_self():
    return SimpleNamespace(system_signals_box=_FakeLabel())


def test_honk_complete_but_no_bodies_scanned_shows_remaining_not_all_discovered():
    fake_self = _fake_self()
    state = SimpleNamespace(
        system_signals=[], system_body_count=3, resolved_body_ids={0}, fss_complete=True,
    )
    ExplorationPanel._refresh_signals(fake_self, state)
    assert "All 3 bodies discovered" not in fake_self.system_signals_box.text
    assert "Bodies resolved: 1/3" in fake_self.system_signals_box.text


def test_all_bodies_actually_resolved_shows_all_discovered():
    fake_self = _fake_self()
    state = SimpleNamespace(
        system_signals=[], system_body_count=3, resolved_body_ids={0, 1, 2}, fss_complete=True,
    )
    ExplorationPanel._refresh_signals(fake_self, state)
    assert "All 3 bodies discovered" in fake_self.system_signals_box.text


def test_all_bodies_resolved_even_without_fss_complete_still_shows_all_discovered():
    # fss_complete tracks the spectrum sweep, not body resolution -- a
    # false/stale value here must not block the correct "all discovered"
    # message once every body genuinely has been scanned.
    fake_self = _fake_self()
    state = SimpleNamespace(
        system_signals=[], system_body_count=3, resolved_body_ids={0, 1, 2}, fss_complete=False,
    )
    ExplorationPanel._refresh_signals(fake_self, state)
    assert "All 3 bodies discovered" in fake_self.system_signals_box.text
