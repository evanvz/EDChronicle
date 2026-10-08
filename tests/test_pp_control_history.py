"""pp_control_history: a controlled system's reinforcement/undermining
control points this cycle (journal + EDDN), the card chip, and the
"undermined since tick" alerts. Ekono readings from Evan's journal."""
from edc.core import bgs_tasks as bt
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

EKONO = 3205949786483
from datetime import datetime, timezone
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)   # cycle started Thu 2026-10-01
NEXT = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)   # after the 10-08 reset
W = {EKONO: "PowerPlay task"}


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (?, 'Ekono')", (EKONO,))
    repo.db.execute(
        "INSERT INTO bgs_tasks (system_address, system_name, task_type, sort_order, created_at) "
        "VALUES (?, 'Ekono', 'powerplay', 0, '2026-10-01')", (EKONO,))
    return repo


def test_only_newer_changed_readings_are_stored(tmp_path):
    repo = _repo(tmp_path)
    assert repo.record_pp_control(EKONO, "2026-10-05T10:00:00Z", "Stronghold", 1500, 3200, 0.28, "journal")
    assert not repo.record_pp_control(EKONO, "2026-10-05T12:00:00Z", "Stronghold", 1500, 3200, 0.28, "eddn")
    assert not repo.record_pp_control(EKONO, "2026-10-04T12:00:00Z", "Stronghold", 1, 1, 0.28, "eddn")
    assert repo.record_pp_control(EKONO, "2026-10-06T16:12:56Z", "Stronghold", 1910, 5333, 0.27, "journal")
    assert repo.get_pp_control_reading(EKONO)["undermining"] == 5333
    assert repo.get_pp_control_reading(EKONO, "2026-10-06T00:00:00Z")["undermining"] == 3200


def test_alert_when_undermining_grew_since_tick_and_leads(tmp_path):
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-10-05T10:00:00Z", "Stronghold", 1500, 3200, 0.28, "journal")
    repo.record_pp_control(EKONO, "2026-10-06T16:12:56Z", "Stronghold", 1910, 5333, 0.27, "journal")
    assert bt.undermining_alerts(repo, "2026-10-06T00:00:00Z", W, NOW) == [("Ekono", 2133, 5333, 1910, "PowerPlay task")]
    # reinforcement ahead -> no alert
    repo.record_pp_control(EKONO, "2026-10-06T20:00:00Z", "Stronghold", 6000, 5400, 0.3, "eddn")
    assert bt.undermining_alerts(repo, "2026-10-06T00:00:00Z", W, NOW) == []


def test_reading_right_after_the_reset_is_not_an_alert(tmp_path):
    """The reset's decay shows up as undermining; with no reading from this
    cycle before the tick there's nothing to compare with -> no alert."""
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-10-07T20:00:00Z", "Stronghold", 900, 5000, 0.3, "eddn")
    repo.record_pp_control(EKONO, "2026-10-08T12:00:00Z", "Stronghold", 10, 400, 0.3, "eddn")  # after Thursday reset
    assert bt.undermining_alerts(repo, "2026-10-08T00:00:00Z", W, NEXT) == []
    # a later rise within the cycle, compared with that first reading, is
    repo.record_pp_control(EKONO, "2026-10-09T12:00:00Z", "Stronghold", 10, 900, 0.3, "eddn")
    later = NEXT.replace(day=9, hour=13)
    assert bt.undermining_alerts(repo, "2026-10-09T00:00:00Z", W, later) == [("Ekono", 500, 900, 10, "PowerPlay task")]


def test_card_chip_shows_real_totals_and_your_share(tmp_path):
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-10-02T17:27:31Z", "Stronghold", 398, 5333, 0.27, "journal")
    repo.record_pp_control(EKONO, "2026-10-06T16:12:56Z", "Stronghold", 1910, 5333, 0.27, "journal")
    view = {"chips": []}
    bt._add_control_chip(view, repo, EKONO, 948, NOW)
    chip = view["chips"][0]
    assert chip["text"] == "Reinforced 1,910 vs decay ≈5,333 · 3,423 to break even · your share ≈237 (12%)"
    assert chip["color"] == "#FFB347"   # decay only: amber, not "under attack"


def test_watch_list_tasks_supporting_and_squad_systems(tmp_path):
    """Dynamic: Tucanae (Acquisition task) pulls in its supporting systems;
    squad-faction systems Aisling holds are added; others aren't."""
    from datetime import date
    from types import SimpleNamespace
    repo = _repo(tmp_path)   # Ekono PowerPlay task (Stronghold)
    TUC, KAU, ISI, FAR = 7268828915161, 3107643593450, 5031788909290, 99
    for addr, name, xyz in ((TUC, "Tucanae Sector DW-V b2-3", (62.28, -203.31, 121.13)),
                            (KAU, "Kauruku", (85.16, -184.94, 118.19)), (ISI, "Isiti", (73.38, -203.78, 100.88)),
                            (FAR, "Far Away", (500.0, 0.0, 0.0)), (EKONO, "Ekono", (59.1, -155.2, 99.8))):
        repo.db.execute("INSERT OR IGNORE INTO systems (system_address, system_name) VALUES (?, ?)", (addr, name))
        repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", (name, *xyz))
    repo.db.execute("INSERT INTO bgs_tasks (system_address, system_name, task_type, pp_mode, sort_order, created_at) "
                    "VALUES (?, 'Tucanae Sector DW-V b2-3', 'powerplay', 'Acquisition', 1, '2026-10-01')", (TUC,))
    for addr in (ISI, FAR):
        repo.save_faction_snapshot(addr, {"Name": "Elite United Worlds", "Influence": 0.2, "SquadronFaction": True},
                                   date.today().isoformat(), True, "2026-10-06T00:00:00Z", "journal")
    edsm = SimpleNamespace(fetched_date="t", held_systems=lambda power, states=None: {
        "Kauruku": "Stronghold", "Isiti": "Stronghold", "Far Away": "Fortified"})
    bt._held_cache.clear()
    watch = bt.pp_watch(repo, "Aisling Duval", edsm)
    assert watch[EKONO] == "PowerPlay task" and watch[TUC] == "PowerPlay task"
    assert watch[KAU] == "supports Tucanae Sector DW-V b2-3"
    assert watch[ISI] == "supports Tucanae Sector DW-V b2-3"   # first reason wins
    assert watch[FAR] == "squad system"


def test_watch_rows_losing_first_and_no_data_rows(tmp_path):
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (5, 'Kauruku'), (6, 'Lagar')")
    repo.record_pp_control(EKONO, "2026-10-02T17:27:31Z", "Stronghold", 398, 5333, 0.27, "journal")
    repo.record_pp_control(5, "2026-10-02T10:00:00Z", "Stronghold", 0, 1200, 0.25, "eddn")
    repo.record_pp_control(EKONO, "2026-10-06T16:12:56Z", "Stronghold", 1910, 5333, 0.27, "journal")
    repo.record_pp_control(5, "2026-10-06T10:00:00Z", "Stronghold", 900, 1200, 0.25, "eddn")
    watch = {EKONO: "PowerPlay task", 5: "supports Tucanae", 6: "squad system"}
    rows = bt.watch_rows(repo, "2026-10-06T00:00:00Z", watch, NOW)
    assert [r["name"] for r in rows] == ["Ekono", "Kauruku", "Lagar"]   # behind on decay, biggest gap first; no data last
    assert rows[0]["status"] == "decay" and not rows[0]["losing"] and rows[0]["gained"] == 0
    assert rows[2]["undermining"] is None and not rows[2]["losing"]


def test_reading_from_an_earlier_cycle_counts_as_no_data(tmp_path):
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-08-16T10:00:00Z", "Exploited", 0, 191, 0.2, "journal")   # 52 days old
    rows = bt.watch_rows(repo, "2026-10-06T00:00:00Z", {EKONO: "squad system"}, NOW)
    assert rows[0]["undermining"] is None and not rows[0]["losing"]
    view = {"chips": []}
    bt._add_control_chip(view, repo, EKONO, 0, NOW)
    assert view["chips"] == []


def test_undermining_that_grows_during_the_cycle_is_an_attack(tmp_path):
    """Ys, 2026-10-07: undermining rose after the reset -> attack; Ekono's
    stayed at its reset value all week -> decay only."""
    repo = _repo(tmp_path)
    repo.record_pp_control(EKONO, "2026-10-02T17:27:31Z", "Stronghold", 398, 5333, 0.27, "journal")
    repo.record_pp_control(EKONO, "2026-10-07T20:33:48Z", "Stronghold", 3953, 5333, 0.27, "eddn")
    YS = 77
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (77, 'Ys')")
    repo.record_pp_control(YS, "2026-10-03T10:00:00Z", "Exploited", 0, 0, 0.3, "eddn")
    repo.record_pp_control(YS, "2026-10-07T12:00:00Z", "Exploited", 33, 1302, 0.3, "eddn")
    ek, ys = bt.control_status(repo, EKONO, NOW), bt.control_status(repo, YS, NOW)
    assert (ek["status"], ek["decay"], ek["attack"]) == ("decay", 5333, 0)
    assert (ys["status"], ys["decay"], ys["attack"]) == ("attack", 0, 1302)
    rows = bt.watch_rows(repo, "2026-10-07T00:00:00Z", {EKONO: "PowerPlay task", YS: "squad system"}, NOW)
    assert [r["name"] for r in rows] == ["Ys", "Ekono"]   # real attack first


def test_late_first_reading_means_split_unknown(tmp_path):
    """EDDN collection began 2026-10-07, six days into the cycle: Ys's 1,302
    undermining can't be split into decay vs attack."""
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (77, 'Ys')")
    repo.record_pp_control(77, "2026-10-07T12:00:00Z", "Exploited", 33, 1302, 0.3, "eddn")
    cs = bt.control_status(repo, 77, NOW)
    assert cs["status"] == "unknown"
    view = {"chips": []}
    bt._add_control_chip(view, repo, 77, 0, NOW)
    assert "decay or attack?" in view["chips"][0]["text"]
    assert bt.undermining_alerts(repo, "2026-10-07T00:00:00Z", {77: "squad system"}, NOW) == []
