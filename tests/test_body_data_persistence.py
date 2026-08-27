"""Personally-scanned bodies were never written to the local DB during live
play -- only journal_importer.py's one-time startup backfill ever called
repo.save_body(), so resolved_body_ids for a scanned planet was lost the
moment you left and returned to a system within the same session (no
reload needed). Confirmed live: 27/27 resolved dropped to 1/27 on a
same-session revisit. This tests the read-side half of the fix --
SystemDataLoader.load_current_system_data() restoring resolved_body_ids
from a body that's actually in the local DB -- proving that once
MainWindow._save_body_data() writes it (the other half, not unit-testable
without Qt), the existing restore path picks it up correctly. Real
SQLite (temp file) and real Repository, matching this repo's convention
(see test_footfall_tracking.py)."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.core.state import GameState
from edc.ui.system_data_loader import SystemDataLoader


def _loader(state, repo):
    return SystemDataLoader(
        state=state,
        repo=repo,
        planet_values=None,
        on_refresh_exploration=lambda: None,
        on_refresh_materials_shortlist=lambda: None,
        on_refresh_exobiology=lambda: None,
        planet_value_class_name_fn=lambda x: x,
    )


def test_personally_scanned_body_survives_a_revisit(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    system_address = 12345
    repo.save_body(
        system_address=system_address, body_id=3, body_name="Test System 3",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=50000, distance_ls=200.0,
    )

    state = GameState()
    state.system_address = system_address
    loader = _loader(state, repo)
    loader.load_current_system_data()

    assert 3 in state.resolved_body_ids
    assert "Test System 3" in state.bodies


def test_resolved_star_survives_a_revisit(tmp_path):
    # Stars have no PlanetClass, so they never go through save_body/get_bodies
    # -- resolved_bodies is the only durable record they were ever scanned.
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    system_address = 12345
    repo.save_resolved_body(system_address, 0)  # BodyID 0 is commonly the entry star

    state = GameState()
    state.system_address = system_address
    loader = _loader(state, repo)
    loader.load_current_system_data()

    assert 0 in state.resolved_body_ids


def test_nsp_phenomena_codex_entry_survives_a_revisit(tmp_path):
    # A Notable Stellar Phenomena confirmation has no body of its own
    # (BodyName "Space") -- codex_entries is body_id-keyed, so it doesn't
    # need a matching state.bodies entry to restore, unlike get_exobiology.
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    system_address = 12345
    repo.save_codex_entry(
        system_address=system_address, body_id=1, genus="Purpureum",
        species="Purpureum Metallic Crystals", variant="Purpureum Metallic Crystals",
        codex_entry_id=2100802, codex_name="Purpureum Metallic Crystals",
        base_value=2500, is_phenomena=1,
    )

    state = GameState()
    state.system_address = system_address
    loader = _loader(state, repo)
    loader.load_current_system_data()

    rec = state.exo.get("1|Purpureum|CODEX")
    assert rec is not None
    assert rec["Complete"] is True
    assert rec["BodyName"] == "Space"


def test_spansh_only_body_gets_a_footfall_estimate(tmp_path):
    # A body Spansh knows about but nobody has personally scanned yet --
    # this is the pre-visit case footfall_predictor.py exists for.
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    system_address = 12345
    repo.save_spansh_body(
        system_address=system_address, body_name="Test System 4",
        planet_class="Rocky body", distance_ls=300.0, estimated_value=None,
        landable=1, was_mapped=0, updated_at="2019-01-01T00:00:00Z",
    )

    state = GameState()
    state.system_address = system_address
    loader = _loader(state, repo)
    loader.load_current_system_data()

    rec = state.bodies.get("Test System 4")
    assert rec is not None
    assert rec["FootfallEstimateScore"] == 100
    assert rec["FootfallEstimateLabel"] == "Likely unclaimed"


def test_personally_scanned_body_has_no_footfall_estimate(tmp_path):
    # Once a body's actually been scanned, the real WasFootfalled/HasFootfall
    # fields take over -- no estimate should be stamped for it.
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    repo = Repository(db)

    system_address = 12345
    repo.save_body(
        system_address=system_address, body_id=3, body_name="Test System 3",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=50000, distance_ls=200.0,
    )

    state = GameState()
    state.system_address = system_address
    loader = _loader(state, repo)
    loader.load_current_system_data()

    rec = state.bodies.get("Test System 3")
    assert rec is not None
    assert rec.get("FootfallEstimateScore") is None
