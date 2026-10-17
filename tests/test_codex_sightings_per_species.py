"""A body can hold several exobiology species: EDDN codex sightings keep one
row per species (they used to overwrite each other, one per body)."""
import sqlite3
from types import SimpleNamespace

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    return Repository(db)


def test_old_one_per_body_table_is_rebuilt(tmp_path):
    net = sqlite3.connect(tmp_path / "network_cache.db")
    net.execute("CREATE TABLE codex_species_sightings (system_address INTEGER NOT NULL, body_id INTEGER NOT NULL, "
                "species_name TEXT NOT NULL, species_symbol TEXT, last_seen TEXT NOT NULL, "
                "PRIMARY KEY (system_address, body_id))")
    net.execute("INSERT INTO codex_species_sightings VALUES (1, 2, 'Silicate Vapour Gas Vent', 'x', '2026-10-17')")
    net.commit(); net.close()
    repo = _repo(tmp_path)
    assert repo.get_codex_species_sightings_for_system(1) == {}


def test_two_species_on_one_body_both_kept_and_counted_once(tmp_path):
    repo = _repo(tmp_path)
    repo.save_codex_species_sightings_batch([
        (42, 7, "Stratum Paleas - Emerald", "$a;", "2026-10-17T10:00:00Z"),
        (42, 7, "Bacterium Aurasus - Teal", "$b;", "2026-10-17T10:01:00Z"),
        (42, 7, "Stratum Paleas - Emerald", "$a;", "2026-10-17T11:00:00Z")])     # repeat: refresh only
    sightings = repo.get_codex_species_sightings_for_system(42)
    assert sorted(s["species_name"] for s in sightings[7]) == ["Bacterium Aurasus - Teal", "Stratum Paleas - Emerald"]

    from edc.ui.main_window import MainWindow
    fake = SimpleNamespace(
        cfg=SimpleNamespace(min_planet_value_100k=5, exo_high_value_m=2), exo_values=None,
        state=SimpleNamespace(system_address=42, rings={},
                              bodies={"A 1": {"BodyID": 7, "BioSignals": 2, "BioGenuses": []}}),
        repo=repo, _spansh_rings_by_system={}, _codex_sightings_cache={}, _codex_sightings_cache_system=None)
    out = MainWindow._compute_action_state(fake)
    line = [l for l in out["exobiology"] if "EDDN-confirmed" in l][0]
    assert line.startswith("🔬 Action: 1 body EDDN-confirmed") and "Bacterium Aurasus - Teal" in line
