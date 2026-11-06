"""The Expansion tracker's lookup asks EDDataHub first, EDSM only as the fallback."""
import json
from edc.utils.dates import utc_today
from unittest.mock import MagicMock

from edc.ui.panels import faction_expansion_dialog as dlg
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

HUB = {"system_address": 42, "system_name": "Delta Indi", "factions": [], "conflicts": [], "updated": "x"}
EDSM = {"system_address": 42, "system_name": "Delta Indi", "factions": []}


def _run(monkeypatch, hub_answer, url="http://hub", address=42):
    hub_calls, edsm_calls, out = [], [], []
    monkeypatch.setattr(dlg, "fetch_hub_factions", lambda u, a: hub_calls.append((u, a)) or hub_answer)
    monkeypatch.setattr(dlg, "fetch_system_factions", lambda n: edsm_calls.append(n) or (EDSM, None))
    worker = dlg._ExpansionLookupWorker("Delta Indi", url, address)
    worker.finished.connect(lambda *a: out.append(a))
    worker.run()
    return out[0], hub_calls, edsm_calls


def test_hub_answer_skips_edsm_and_is_marked_hub(monkeypatch):
    (result, error, name), hub_calls, edsm_calls = _run(monkeypatch, {42: HUB})
    assert result["source"] == "hub" and result["system_name"] == "Delta Indi"
    assert error is None and name == "Delta Indi"
    assert hub_calls == [("http://hub", [42])] and edsm_calls == []


def test_hub_down_falls_back_to_edsm(monkeypatch):
    (result, _, _), _, edsm_calls = _run(monkeypatch, None)
    assert result is EDSM and edsm_calls == ["Delta Indi"]


def test_system_missing_from_hub_falls_back_to_edsm(monkeypatch):
    (result, _, _), _, edsm_calls = _run(monkeypatch, {})
    assert result is EDSM and edsm_calls == ["Delta Indi"]


def test_unknown_address_falls_back_to_edsm(monkeypatch):
    (result, _, _), _, edsm_calls = _run(monkeypatch, None, address=None)
    assert result is EDSM and edsm_calls == ["Delta Indi"]


def test_lookup_saves_rivals_so_conflict_checks_see_them(tmp_path):
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    fake = MagicMock()
    fake._panel._repo = repo
    fake._panel._faction_name = "EUW"
    ts = f"{utc_today().isoformat()}T12:00:00Z"
    result = {"system_address": 42, "system_name": "Delta Indi", "source": "hub", "factions": [
        {"Name": "EUW", "Influence": 0.5, "ActiveStates": [{"State": "War"}], "is_controlling": True, "LastUpdate": ts},
        {"Name": "Rival", "Influence": 0.5, "ActiveStates": [{"State": "War"}], "is_controlling": False, "LastUpdate": ts},
    ]}
    dlg.FactionExpansionDialog._on_lookup_finished(fake, result, None, "Delta Indi")
    assert repo.get_faction_history(42, "EUW")[0]["influence"] == 0.5
    assert repo.get_faction_history(42, "Rival")[0]["influence"] == 0.5
    assert repo.db.execute("SELECT source, is_controlling FROM faction_snapshots WHERE faction_name='Rival'").fetchone()[:2] == ("hub", 0)
    assert repo._war_corroborated(42, "EUW", None, json.dumps([{"State": "War"}]), utc_today().isoformat()) is True
