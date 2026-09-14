"""MaterialsPanel's ShipLocker storage cards (Assets/Goods/Consumables/
Data) -- each has its own independent 1000-slot cap in-game (confirmed
against the real in-game Storage screen), so the Materials tab shows one
capacity card per category instead of folding them into the Raw/
Manufactured/Encoded dropdown+table. Uses the fake-self/MagicMock pattern
already established for panel tests (see
test_combat_bgs_status_click_to_copy.py) since no test in this suite
constructs a real QWidget tree -- confirmed no test exists for
planet_detail_dialog.py either, the precedent for this panel's detail
dialog."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.ui.panels.inventory_panel import MaterialsPanel


def test_refresh_storage_cards_sums_category_counts():
    cap_lbl = MagicMock()
    fake_self = SimpleNamespace(_storage_cards={"Assets": cap_lbl})
    state = SimpleNamespace(
        shiplocker_by_category={"Assets": {"circuitboard": 25, "graphene": 30}}
    )
    MaterialsPanel.refresh_storage_cards(fake_self, state)
    cap_lbl.setText.assert_called_once_with("55/1000")


def test_refresh_storage_cards_zero_when_category_empty():
    cap_lbl = MagicMock()
    fake_self = SimpleNamespace(_storage_cards={"Data": cap_lbl})
    state = SimpleNamespace(shiplocker_by_category={})
    MaterialsPanel.refresh_storage_cards(fake_self, state)
    cap_lbl.setText.assert_called_once_with("0/1000")


def test_refresh_storage_cards_updates_every_tracked_category():
    assets_lbl, goods_lbl = MagicMock(), MagicMock()
    fake_self = SimpleNamespace(_storage_cards={"Assets": assets_lbl, "Goods": goods_lbl})
    state = SimpleNamespace(
        shiplocker_by_category={"Assets": {"circuitboard": 10}, "Goods": {"gmeds": 5}}
    )
    MaterialsPanel.refresh_storage_cards(fake_self, state)
    assets_lbl.setText.assert_called_once_with("10/1000")
    goods_lbl.setText.assert_called_once_with("5/1000")
