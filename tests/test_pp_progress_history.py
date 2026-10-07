"""pp_progress_history: acquisition progress changes per system/power,
and the BGS Tasks trend chip built from them. Readings from Evan's
journal for Tucanae Sector DW-V b2-3, 2026-10-02/03."""
from edc.core import bgs_tasks as bt
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

ADDR = 7268828915161


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_only_changes_are_stored(tmp_path):
    repo = _repo(tmp_path)
    p = "Aisling Duval"
    assert repo.record_pp_progress(ADDR, {p: 0.835067}, "2026-10-02T20:06:23Z", "journal") == 1
    assert repo.record_pp_progress(ADDR, {p: 0.835067}, "2026-10-02T22:06:52Z", "journal") == 0
    assert repo.record_pp_progress(ADDR, {p: 0.8361}, "2026-10-03T09:54:03Z", "journal") == 1
    assert repo.record_pp_progress(ADDR, {p: 0.8361}, "2026-10-03T08:00:00Z", "eddn") == 0  # older
    assert repo.record_pp_progress(ADDR, {p: 0.83935}, "2026-10-03T11:50:25Z", "eddn") == 1
    assert [h[1] for h in repo.get_pp_progress_history(ADDR, p)] == [0.83935, 0.8361, 0.835067]


def test_trend_chip_with_merits_between_readings(tmp_path):
    repo = _repo(tmp_path)
    p = "Aisling Duval"
    repo.record_pp_progress(ADDR, {p: 0.8361}, "2026-10-03T09:54:03Z", "journal")
    repo.record_pp_progress(ADDR, {p: 0.83935}, "2026-10-03T11:50:25Z", "journal")
    repo.record_powerplay_merits(ADDR, p, 1716, "2026-10-03T10:22:13Z")
    repo.record_powerplay_merits(ADDR, p, 1650, "2026-10-03T11:00:37Z")
    view = {"chips": []}
    bt._add_progress_trend(view, repo, ADDR, p)
    chip = view["chips"][0]
    assert chip["text"] == "+0.33% since 10-03 09:54"
    assert "+0.325% (journal) · your merits here: 3,366" in chip["tooltip"]


def test_cp_estimate_and_week_total(tmp_path):
    repo = _repo(tmp_path)
    repo.record_powerplay_merits(ADDR, "Aisling Duval", 1650, "2026-10-03T11:00:37Z")
    repo.record_powerplay_merits(ADDR, "Aisling Duval", 1716, "2026-10-03T10:22:13Z")
    repo.record_powerplay_merits(ADDR, "Aisling Duval", 999, "2026-09-30T10:00:00Z")
    assert repo.get_powerplay_merits_total_since("2026-10-01T07:00:00Z") == 3366
    assert bt.cp_text(3366) == "≈842 CP"


def test_rank_up_makes_the_next_load_ready(tmp_path):
    """20:20 collect, 20:27 rank-up -> bonus load (collected 20:33 in game)."""
    from datetime import datetime, timezone
    from edc.core.event_engine import EventEngine
    from edc.core.state import GameState
    eng = EventEngine(GameState(), tmp_path)
    eng.state.pp_last_collect = {"aisling media materials": "2026-10-03T20:20:18Z"}
    eng.process({"timestamp": "2026-10-03T20:27:02Z", "event": "PowerplayRank", "Power": "Aisling Duval", "Rank": 176})
    assert eng.state.pp_rank == 176
    info = bt.commodity_info("Acquisition", "Aisling Duval", {}, eng.state.pp_last_collect,
                             now=datetime(2026, 10, 3, 20, 28, tzinfo=timezone.utc))
    assert info["next_allocation"] == "now"
