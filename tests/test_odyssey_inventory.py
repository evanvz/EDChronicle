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


def test_backpack_fields_exist_on_state():
    state = GameState()
    assert state.backpack_items == {}
    assert state.backpack_localised == {}


def test_backpackchange_added_increments_backpack_items(engine):
    event = {
        "event": "BackpackChange",
        "Added": [
            {"Name": "healthpack", "Name_Localised": "Medkit", "OwnerID": 0, "Count": 2, "Type": "Consumable"},
        ],
    }
    handled = inventory.handle(engine, "BackpackChange", event, [])
    assert handled is True
    assert engine.state.backpack_items == {"healthpack": 2}
    assert engine.state.backpack_localised == {"healthpack": "Medkit"}


def test_backpackchange_removed_decrements_and_removes_at_zero(engine):
    engine.state.backpack_items = {"healthpack": 2}
    engine.state.backpack_localised = {"healthpack": "Medkit"}
    event = {
        "event": "BackpackChange",
        "Removed": [
            {"Name": "healthpack", "OwnerID": 0, "Count": 2, "Type": "Consumable"},
        ],
    }
    inventory.handle(engine, "BackpackChange", event, [])
    assert "healthpack" not in engine.state.backpack_items


def test_backpackchange_removed_partial_keeps_remainder(engine):
    engine.state.backpack_items = {"healthpack": 5}
    event = {
        "event": "BackpackChange",
        "Removed": [{"Name": "healthpack", "OwnerID": 0, "Count": 2, "Type": "Consumable"}],
    }
    inventory.handle(engine, "BackpackChange", event, [])
    assert engine.state.backpack_items == {"healthpack": 3}


def test_backpackchange_added_and_removed_in_same_event(engine):
    # A single BackpackChange can carry both arrays at once (e.g. crafting
    # something that consumes one material and produces another).
    event = {
        "event": "BackpackChange",
        "Added": [{"Name": "rdx", "Name_Localised": "RDX", "OwnerID": 0, "Count": 1, "Type": "Component"}],
        "Removed": [{"Name": "graphene", "OwnerID": 0, "Count": 1, "Type": "Component"}],
    }
    engine.state.backpack_items = {"graphene": 1}
    inventory.handle(engine, "BackpackChange", event, [])
    assert engine.state.backpack_items == {"rdx": 1}


def test_bootstrap_replay_does_not_double_apply_backpackchange_over_disk_snapshot(tmp_path, engine):
    # Reproduces the bootstrap-replay bug: Backpack.json on disk already
    # reflects the CURRENT truth (healthpack: 3). During replay, a
    # "Backpack" event triggers a disk re-read (correct: 3), but a
    # "BackpackChange" event later in the same replay window (the game's
    # normal embark/disembark sequence) then applies its delta ON TOP of
    # that already-current snapshot, double-counting it. MainWindow's
    # "_BootstrapEnd" handling must do one final authoritative re-read of
    # both on-foot inventory files so the end state matches disk truth
    # regardless of what replayed deltas did in between.
    _write_json(tmp_path / "Backpack.json", {
        "Items": [], "Components": [], "Data": [],
        "Consumables": [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 3}],
    })
    fake_self = SimpleNamespace(
        cfg=SimpleNamespace(journal_dir=str(tmp_path)),
        engine=engine,
        state=engine.state,
        eddn_publisher=SimpleNamespace(observe=lambda evt: None),
        engineering_panel=SimpleNamespace(refresh=lambda state: None),
        _append=lambda text: None,
        _refresh_engineering=lambda: None,
        _schedule_hud_refresh=lambda: None,
    )
    fake_self._load_backpack_inventory = lambda: MainWindow._load_backpack_inventory(fake_self)
    fake_self._load_shiplocker_inventory = lambda: MainWindow._load_shiplocker_inventory(fake_self)

    MainWindow._on_event(fake_self, {"event": "_BootstrapStart"})
    MainWindow._on_event(fake_self, {"event": "Backpack"})
    assert fake_self.state.backpack_items == {"healthpack": 3}

    MainWindow._on_event(fake_self, {
        "event": "BackpackChange",
        "Removed": [{"Name": "healthpack", "OwnerID": 0, "Count": 2, "Type": "Consumable"}],
    })
    # Bug: delta applied on top of the already-current disk snapshot.
    assert fake_self.state.backpack_items == {"healthpack": 1}

    MainWindow._on_event(fake_self, {"event": "_BootstrapEnd"})
    # After replay ends, the authoritative re-read must win: disk truth is 3.
    assert fake_self.state.backpack_items == {"healthpack": 3}


def test_load_backpack_inventory_reads_all_four_categories_from_disk(tmp_path, engine):
    # Genuine end-to-end integration test for MainWindow._load_backpack_inventory()
    # itself (not just the underlying parse helper): a real Backpack.json on
    # disk, all four category arrays populated with distinct materials so a
    # bug that only reads one category would fail this test.
    _write_json(
        tmp_path / "Backpack.json",
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
    MainWindow._load_backpack_inventory(fake_self)
    assert fake_self.state.backpack_items == {"graphene": 3, "rdx": 5, "biometricdata": 1, "healthpack": 2}
    assert fake_self.state.backpack_localised == {
        "graphene": "Graphene",
        "rdx": "RDX",
        "biometricdata": "Biometric Data",
        "healthpack": "Medkit",
    }
