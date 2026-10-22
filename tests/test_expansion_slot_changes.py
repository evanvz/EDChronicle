"""Expansion Forecast: live EDDN faction counts for the candidate systems. A
change that moves a candidate across the 7-faction line (a slot filled, or a
retreat opened one) is flagged; drift that doesn't change its role isn't."""
from datetime import date, datetime, timedelta, timezone

from edc.core.expansion_forecast import (
    merge_live_counts, slot_change_text, slot_changes, slot_kind,
)

TODAY = date(2026, 10, 11)


def _live(count, prev=None, changed=None, ts="2026-10-11T08:00:00Z", factions=None):
    return {"system_name": "Arimavante", "faction_count": count, "prev_count": prev,
            "changed_at": changed, "data_timestamp": ts,
            "factions": factions if factions is not None else [f"F{i}" for i in range(count)]}


def test_slot_kind():
    assert [slot_kind(n) for n in (None, 3, 6, 7, 8)] == [None, "slot", "slot", "invasion", "full"]


def test_slot_changes_only_flags_crossing_the_line_within_days():
    live = {
        1: _live(7, prev=6, changed="2026-10-11T07:00:00Z"),            # slot filled
        2: {**_live(5, prev=4, changed="2026-10-11T07:00:00Z"), "system_name": "Drift"},  # still a slot
        3: {**_live(6, prev=7, changed="2026-10-05T07:00:00Z"), "system_name": "Old"},    # > 3 days ago
        4: {**_live(6, prev=7, changed="2026-10-10T07:00:00Z"), "system_name": "Opened"}, # retreat opened one
    }
    got = slot_changes(live, TODAY)
    assert [c["system_name"] for c in got] == ["Arimavante", "Opened"]  # newest first
    # our own arrival filled it (Arimavante 2026-10-22): not a target, not flagged
    live[1] = _live(7, prev=6, changed="2026-10-11T07:00:00Z", factions=[f"F{i}" for i in range(6)] + ["EUW"])
    assert [c["system_name"] for c in slot_changes(live, TODAY, faction="EUW")] == ["Opened"]


def test_slot_change_text():
    assert slot_change_text({"system_name": "Arimavante", "prev_count": 6, "faction_count": 7,
                             "changed_at": "2026-10-11T07:00:00Z"}) == (
        "⚠ Arimavante: 6 → 7 factions (10-11) — its free slot is gone; now an invasion target")
    assert slot_change_text({"system_name": "X", "prev_count": 7, "faction_count": 6,
                             "changed_at": "2026-10-10T07:00:00Z"}, "Y") == (
        "⚠ X: 7 → 6 factions (10-10) — a faction left; free slot open · likely target now Y")
    assert "no longer a target" in slot_change_text(
        {"system_name": "X", "prev_count": 7, "faction_count": 8, "changed_at": "2026-10-10T07:00:00Z"})


def test_merge_prefers_a_live_eddn_reading():
    cached = [
        {"system_name": "Arimavante", "system_address": 1, "faction_count": 6, "faction_present": False,
         "fetched_at": "2026-10-10T12:00:00Z"},
        {"system_name": "Fresh", "system_address": 2, "faction_count": 5, "faction_present": False,
         "fetched_at": "2026-10-11T12:00:00Z"},
    ]
    live = {1: _live(7, prev=6, changed="2026-10-11T07:00:00Z", factions=["A", "B", "C", "D", "E", "F", "Euw"]),
            2: {**_live(6), "system_name": "Fresh", "data_timestamp": "2026-10-11T08:00:00Z"}}
    live.pop(2)
    cached.append({"system_name": "NoLive", "system_address": 3, "faction_count": 4, "faction_present": False,
                   "fetched_at": "2026-10-11T12:00:00Z"})
    merged = merge_live_counts(cached, live, "Euw")
    # EDDN's observation wins even though the EDSM lookup was fetched later (EDSM's data age is unknown)
    assert merged[0]["faction_count"] == 7 and merged[0]["faction_present"] and merged[0]["count_source"] == "EDDN"
    assert merged[2]["faction_count"] == 4 and "count_source" not in merged[2]  # no live reading: EDSM


def _repo(tmp_path):
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_repository_records_a_count_change_against_edsm_then_eddn(tmp_path):
    repo = _repo(tmp_path)
    repo.save_expansion_candidates(99, [{"system_name": "Arimavante", "system_address": 1, "distance_ly": 9.0,
                                         "faction_count": 6}], "2026-10-10T12:00:00Z")
    assert repo.get_expansion_candidate_addresses() == {1}

    six = ["A", "B", "C", "D", "E", "F"]
    repo.save_candidate_faction_count(1, "Arimavante", six, "2026-10-10T20:00:00Z")
    row = repo.get_candidate_faction_counts()[1]
    assert row["faction_count"] == 6 and row["changed_at"] is None  # same as EDSM: no change

    repo.save_candidate_faction_count(1, "Arimavante", six + ["New"], "2026-10-11T07:00:00Z")
    row = repo.get_candidate_faction_counts()[1]
    assert (row["prev_count"], row["faction_count"], row["changed_at"]) == (6, 7, "2026-10-11T07:00:00Z")
    assert "New" in row["factions"]

    repo.save_candidate_faction_count(1, "Arimavante", six, "2026-10-09T00:00:00Z")  # older: ignored
    assert repo.get_candidate_faction_counts()[1]["faction_count"] == 7

    repo.save_candidate_faction_count(1, "Arimavante", six + ["New"], "2026-10-11T09:00:00Z")  # same count
    assert repo.get_candidate_faction_counts()[1]["changed_at"] == "2026-10-11T07:00:00Z"  # change kept


def test_listener_emits_faction_names_only_for_watched_systems():
    from edc.core.eddn_listener import EddnPowerPlayWorker
    worker = EddnPowerPlayWorker()
    seen = []
    worker.faction_names_seen.connect(lambda *a: seen.append(a))
    msg = {"SystemAddress": 1, "StarSystem": "Arimavante", "Factions": [
        {"Name": "A", "Influence": 0.58}, {"Name": "Gone", "Influence": 0.0}, {"Name": "B", "Influence": 0.1}]}
    worker._maybe_emit_faction_names(msg, "2026-10-11T07:00:00Z")
    assert seen == []                                   # not watched yet
    worker.set_watched_systems({1})
    worker._maybe_emit_faction_names(msg, "2026-10-11T07:00:00Z")
    worker._maybe_emit_faction_names({**msg, "SystemAddress": 2}, "2026-10-11T07:00:00Z")
    assert seen == [(1, "Arimavante", ["A", "B"], "2026-10-11T07:00:00Z")]  # 0% faction not counted


def test_eddn_buffer_writes_through_to_the_table(tmp_path):
    from edc.core.eddn_market import EddnMarketCache, write_buffers
    repo = _repo(tmp_path)
    cache = EddnMarketCache(repo=None)
    cache.on_faction_names_seen(1, "Arimavante", ["A", "B"], "2026-10-11T07:00:00Z")
    write_buffers(repo, *cache.pop_buffers())
    assert repo.get_candidate_faction_counts()[1]["faction_count"] == 2


def test_overview_shows_slot_change_line(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    from edc.ui.main_window import MainWindow
    repo = _repo(tmp_path)
    repo.save_expansion_candidates(99, [{"system_name": "Arimavante", "system_address": 1, "faction_count": 6}],
                                   "2026-10-10T12:00:00Z")
    repo.save_candidate_faction_count(1, "Arimavante", list("ABCDEFG"),
                                    (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    shown = []
    fake = SimpleNamespace(repo=repo, overview_panel=SimpleNamespace(set_new_system_alert=shown.append),
                           player_faction_panel=SimpleNamespace(_faction_name="Euw"))
    with patch("edc.ui.main_window.detect_new_systems", return_value=[]):
        MainWindow._refresh_new_system_alert(fake, force=True)
    assert shown[-1].startswith("⚠ Arimavante: 6 → 7 factions")


def test_future_timestamped_reading_is_rejected(tmp_path):
    """EDDN is unauthenticated: a reading dated in the future would otherwise block
    every genuine later reading and keep its change alert up forever."""
    repo = _repo(tmp_path)
    repo.save_expansion_candidates(99, [{"system_name": "Arimavante", "system_address": 1, "faction_count": 6}],
                                   "2026-10-10T12:00:00Z")
    repo.save_candidate_faction_count(1, "Arimavante", list("ABCDEFG"), "2099-01-01T00:00:00Z")
    assert 1 not in repo.get_candidate_faction_counts()
    repo.save_candidate_faction_count(1, "Arimavante", list("ABCDEF"), "2026-10-11T07:00:00Z")
    assert repo.get_candidate_faction_counts()[1]["faction_count"] == 6
