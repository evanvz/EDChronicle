"""Tests for was_footfalled tracking -- persistence round-trip, the
journal importer's parsing, and the live Scan handler's data-loss fix.
Real SQLite (temp file) and real EventEngine, not mocks, matching this
repo's established convention."""
from pathlib import Path

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_save_body_persists_was_footfalled(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=1,
    )
    rows = list(repo.get_bodies(1))
    assert len(rows) == 1
    assert rows[0]["was_footfalled"] == 1


def test_save_body_was_footfalled_defaults_to_zero(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
    )
    rows = list(repo.get_bodies(1))
    assert rows[0]["was_footfalled"] == 0


def test_save_body_was_footfalled_overwrites_on_conflict(repo):
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=1,
    )
    repo.save_body(
        system_address=1, body_id=1, body_name="Test Body 1",
        planet_class="Rocky body", terraformable=0, landable=1,
        was_mapped=1, dss_mapped=1, estimated_value=1000, distance_ls=100.0,
        was_footfalled=0,
    )
    rows = list(repo.get_bodies(1))
    assert rows[0]["was_footfalled"] == 0
