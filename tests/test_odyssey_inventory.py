"""Tests for Odyssey on-foot inventory tracking -- ShipLocker/Backpack
handlers and file re-reads. Uses a real EventEngine + GameState (not
mocks), matching this repo's established testing convention."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.engine.handlers import inventory
from edc.ui.main_window import MainWindow


@pytest.fixture
def engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_shiplocker_handler_writes_localised_name_to_shiplocker_localised(engine):
    event = {
        "event": "ShipLocker",
        "Items": [
            {"Name": "graphene", "Name_Localised": "Graphene", "Count": 3},
        ],
    }
    handled = inventory.handle(engine, "ShipLocker", event, [])
    assert handled is True
    assert engine.state.shiplocker_items == {"graphene": 3}
    assert engine.state.shiplocker_localised == {"graphene": "Graphene"}


def test_shiplocker_items_loc_field_no_longer_exists(engine):
    assert not hasattr(engine.state, "shiplocker_items_loc")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_parse_shiplocker_items_merges_all_four_categories(engine):
    # This directly exercises the merge logic Task 2's
    # _load_shiplocker_inventory() will use -- four separate category
    # lists, each parsed via the existing _parse_shiplocker_items(),
    # combined into one flat pair with no collisions.
    counts: dict = {}
    loc: dict = {}
    for category_items in (
        [{"Name": "graphene", "Name_Localised": "Graphene", "Count": 3}],
        [{"Name": "rdx", "Name_Localised": "RDX", "Count": 5}],
        [{"Name": "biometricdata", "Name_Localised": "Biometric Data", "Count": 1}],
        [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
    ):
        c, l = engine._parse_shiplocker_items(category_items)
        counts.update(c)
        loc.update(l)
    assert counts == {"graphene": 3, "rdx": 5, "biometricdata": 1, "healthpack": 2}
    assert loc == {"graphene": "Graphene", "rdx": "RDX", "biometricdata": "Biometric Data", "healthpack": "Medkit"}


def test_load_shiplocker_inventory_reads_all_four_categories_from_disk(tmp_path, engine):
    # Exercises MainWindow._load_shiplocker_inventory() itself (not just the
    # helper it calls) end-to-end: a real ShipLocker.json on disk, all four
    # category arrays populated with distinct materials so a bug that only
    # reads one category would fail this test.
    _write_json(
        tmp_path / "ShipLocker.json",
        {
            "Items": [{"Name": "graphene", "Name_Localised": "Graphene", "Count": 3}],
            "Components": [{"Name": "rdx", "Name_Localised": "RDX", "Count": 5}],
            "Data": [{"Name": "biometricdata", "Name_Localised": "Biometric Data", "Count": 1}],
            "Consumables": [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
        },
    )
    fake_self = SimpleNamespace(
        cfg=SimpleNamespace(journal_dir=str(tmp_path)),
        engine=engine,
        state=engine.state,
    )
    MainWindow._load_shiplocker_inventory(fake_self)
    assert fake_self.state.shiplocker_items == {"graphene": 3, "rdx": 5, "biometricdata": 1, "healthpack": 2}
    assert fake_self.state.shiplocker_localised == {
        "graphene": "Graphene",
        "rdx": "RDX",
        "biometricdata": "Biometric Data",
        "healthpack": "Medkit",
    }
