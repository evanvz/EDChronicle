"""Tests for Odyssey on-foot inventory tracking -- ShipLocker/Backpack
handlers and file re-reads. Uses a real EventEngine + GameState (not
mocks), matching this repo's established testing convention."""
from pathlib import Path

import pytest

from edc.core.event_engine import EventEngine
from edc.core.state import GameState
from edc.engine.handlers import inventory


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
