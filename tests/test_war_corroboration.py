"""Repository._war_corroborated() -- a War/CivilWar FactionState on our
own tracked faction shouldn't be trusted at face value; a real BGS war
always has two factions sharing the state. Confirmed live: EDSM reported
a lone faction's FactionState as "War" for days with a frozen
data_timestamp and no opposing faction anywhere in the same system,
which isn't how a real two-sided war looks. get_player_faction_overview()
and get_player_faction_system_status() both attach war_corroborated
(None/True/False) to each system dict; player_faction_panel.py's
_bgs_action_core() downgrades its message when it's False."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.ui.panels.player_faction_panel import _bgs_action_core


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _faction(name, influence=0.5, faction_state="None", squadron=False):
    f = {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}
    if faction_state != "None":
        f["FactionState"] = faction_state
    if squadron:
        f["SquadronFaction"] = True
    return f


def test_war_with_no_opponent_is_not_corroborated(tmp_path):
    repo = _repo(tmp_path)
    repo.save_faction_snapshot(
        1, _faction("Elite United Worlds", influence=0.66, faction_state="War", squadron=True),
        "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm",
    )
    repo.save_faction_snapshot(
        1, _faction("Rival Faction", influence=0.19, faction_state="None"),
        "2026-09-03", False, "2026-08-30T15:20:00Z", "edsm",
    )

    overview = repo.get_player_faction_overview()
    sys_row = overview["systems"][0]
    assert sys_row["faction_state"] == "War"
    assert sys_row["war_corroborated"] is False


def test_war_with_matching_opponent_is_corroborated(tmp_path):
    repo = _repo(tmp_path)
    repo.save_faction_snapshot(
        1, _faction("Elite United Worlds", influence=0.5, faction_state="War", squadron=True),
        "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm",
    )
    repo.save_faction_snapshot(
        1, _faction("Rival Faction", influence=0.45, faction_state="War"),
        "2026-09-03", False, "2026-08-30T15:20:00Z", "edsm",
    )

    overview = repo.get_player_faction_overview()
    sys_row = overview["systems"][0]
    assert sys_row["war_corroborated"] is True


def test_no_war_state_is_not_applicable(tmp_path):
    repo = _repo(tmp_path)
    repo.save_faction_snapshot(
        1, _faction("Elite United Worlds", influence=0.5, faction_state="Boom", squadron=True),
        "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm",
    )

    overview = repo.get_player_faction_overview()
    sys_row = overview["systems"][0]
    assert sys_row["war_corroborated"] is None


def test_get_player_faction_system_status_also_attaches_corroboration(tmp_path):
    repo = _repo(tmp_path)
    repo.save_faction_snapshot(
        1, _faction("Elite United Worlds", influence=0.66, faction_state="War", squadron=True),
        "2026-09-03", True, "2026-08-30T15:20:00Z", "edsm",
    )

    result = repo.get_player_faction_system_status("Elite United Worlds", 1)
    assert result["war_corroborated"] is False


def test_bgs_action_core_downgrades_uncorroborated_war():
    sys_rec = {"faction_state": "War", "war_corroborated": False, "is_controlling": True}
    text, color = _bgs_action_core(sys_rec)
    assert "no opposing faction confirmed" in text
    assert color == "#FFB347"


def test_bgs_action_core_keeps_full_message_when_corroborated():
    sys_rec = {"faction_state": "War", "war_corroborated": True, "is_controlling": True}
    text, color = _bgs_action_core(sys_rec)
    assert text.startswith("⚔ War/Civil War active")
    assert color == "#FF6B6B"


def test_bgs_action_core_defaults_to_full_message_when_field_absent():
    # A caller that never attached war_corroborated (e.g. an older code
    # path) must not be silently downgraded -- only an explicit False
    # (checked-and-not-found) triggers the caveat.
    sys_rec = {"faction_state": "War", "is_controlling": True}
    text, color = _bgs_action_core(sys_rec)
    assert text.startswith("⚔ War/Civil War active")
