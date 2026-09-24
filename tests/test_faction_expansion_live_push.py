"""PlayerFactionPanel.notify_faction_snapshot_saved() -- pushes a zero-
network-cost repaint to the Faction Expansion tracker the instant a live
journal-sourced faction_snapshots write lands for the system it's
tracking, instead of leaving it to catch up on its own next refresh
cycle (up to 2 minutes later). Fake self/dialog, same pattern as
test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.panels.player_faction_panel import PlayerFactionPanel


def _fake_dialog():
    calls = []
    return SimpleNamespace(on_live_snapshot_saved=lambda addr: calls.append(addr)), calls


def test_notifies_the_open_dialog():
    dlg, calls = _fake_dialog()
    fake_self = SimpleNamespace(_faction_expansion_dialog=dlg)
    PlayerFactionPanel.notify_faction_snapshot_saved(fake_self, 12345)
    assert calls == [12345]


def test_noop_when_dialog_never_opened():
    fake_self = SimpleNamespace(_faction_expansion_dialog=None)
    PlayerFactionPanel.notify_faction_snapshot_saved(fake_self, 12345)  # must not raise


# --- FactionExpansionDialog.on_live_snapshot_saved()'s own guard logic ---

from edc.ui.panels.faction_expansion_dialog import FactionExpansionDialog


def _fake_expansion_dialog(system_address, tracked_system_name):
    rendered = []
    return SimpleNamespace(
        _system_address=system_address,
        _tracked_system_name=tracked_system_name,
        _render=lambda name: rendered.append(name),
    ), rendered


def test_repaints_when_the_saved_system_matches_the_tracked_one():
    fs, rendered = _fake_expansion_dialog(system_address=12345, tracked_system_name="Ekono")
    FactionExpansionDialog.on_live_snapshot_saved(fs, 12345)
    assert rendered == ["Ekono"]


def test_ignores_a_different_systems_snapshot():
    fs, rendered = _fake_expansion_dialog(system_address=12345, tracked_system_name="Ekono")
    FactionExpansionDialog.on_live_snapshot_saved(fs, 99999)
    assert rendered == []


def test_ignores_when_nothing_is_tracked_yet():
    fs, rendered = _fake_expansion_dialog(system_address=None, tracked_system_name=None)
    FactionExpansionDialog.on_live_snapshot_saved(fs, 12345)
    assert rendered == []
