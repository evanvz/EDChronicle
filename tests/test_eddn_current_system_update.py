"""Sitting in a system when its BGS update lands: other players' EDDN uploads
refresh the current-system view, once a second upload agrees (stale uploads can
show old values -- the same rule as edc.core.system_ticks)."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow

ARI = 4756911035114


def _win():
    state = SimpleNamespace(
        system_address=ARI, factions_timestamp="2026-10-23T18:46:13Z", system_conflicts=[
            {"WarType": "war", "Status": "pending", "Faction1": {"Name": "CCS", "WonDays": 0},
             "Faction2": {"Name": "EUW", "WonDays": 0}}],
        factions=[{"Name": "EUW", "Influence": 0.1802, "PendingStates": [{"State": "War"}], "SquadronFaction": True},
                  {"Name": "CCS", "Influence": 0.1802, "PendingStates": [{"State": "War"}]}])
    win = SimpleNamespace(state=state, _eddn_pending_reading=None, notes=[])
    win._bgs_reading_key = MainWindow._bgs_reading_key
    win._append = win.notes.append
    win._schedule_hud_refresh = lambda: None
    win._refresh_player_faction = lambda: None
    return win


def _upload(win, ts, days=1, status="active"):
    factions = [{"Name": "EUW", "Influence": 0.1802, "ActiveStates": [{"State": "War"}]},
                {"Name": "CCS", "Influence": 0.1802, "ActiveStates": [{"State": "War"}]}]
    conflicts = [{"WarType": "war", "Status": status, "Faction1": {"Name": "CCS", "WonDays": 0},
                  "Faction2": {"Name": "EUW", "WonDays": days}}]
    MainWindow._on_eddn_current_system(win, ARI, "Arimavante", {"SystemFactions": factions,
                                                                  "SystemConflicts": conflicts}, False, ts)


def test_change_applied_once_a_second_upload_agrees_keeping_our_own_fields():
    win = _win()
    _upload(win, "2026-10-23T19:00:00Z")
    assert win.state.factions[0].get("PendingStates") and not win.notes          # one upload: waits
    _upload(win, "2026-10-23T19:05:00Z")
    assert win.state.system_conflicts[0]["Faction2"]["WonDays"] == 1
    assert win.state.factions[0]["SquadronFaction"] is True                      # kept from our journal
    assert win.notes and "tick has reached Arimavante" in win.notes[0]
    assert win.state.factions_timestamp == "2026-10-23T19:05:00Z"


def test_older_disagreeing_or_other_system_uploads_are_ignored():
    win = _win()
    _upload(win, "2026-10-23T18:00:00Z")                                          # older than our reading
    _upload(win, "2026-10-23T18:10:00Z")
    assert win.state.system_conflicts[0]["Status"] == "pending"
    _upload(win, "2026-10-23T19:00:00Z", days=1)
    _upload(win, "2026-10-23T19:05:00Z", days=0)                                  # disagrees: starts over
    assert win.state.system_conflicts[0]["Status"] == "pending" and not win.notes
    MainWindow._on_eddn_current_system(win, 123, "Elsewhere", {"SystemFactions": [{"Name": "X"}]}, False,
                                       "2026-10-23T20:00:00Z")
    assert win.state.system_conflicts[0]["Status"] == "pending"


def test_listener_forwards_any_system_the_commander_is_in():
    """Not only systems with the squadron faction: the current one, whatever it is."""
    import json, zlib
    from unittest.mock import MagicMock
    from edc.core.eddn_listener import EddnPowerPlayWorker
    w = EddnPowerPlayWorker()          # no watched factions at all
    seen = []
    w.current_system_seen.connect(lambda addr, name, s, c, ts: seen.append((addr, name, len(s["SystemFactions"]))))
    w.set_current_system(99)

    def raw(addr):
        msg = {"event": "FSDJump", "StarSystem": f"S{addr}", "SystemAddress": addr, "StarPos": [0, 0, 0],
               "timestamp": "2026-10-23T19:00:00Z", "Factions": [{"Name": "A", "Influence": 0.6},
                                                                {"Name": "B", "Influence": 0.4}]}
        return zlib.compress(json.dumps({"$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
                                         "header": {"uploaderID": "u"}, "message": msg}).encode())
    sock = MagicMock()
    sock.recv.side_effect = [raw(5), raw(99), KeyboardInterrupt]
    try:
        w._pump(sock)
    except KeyboardInterrupt:
        pass
    assert seen == [(99, "S99", 2)]
