"""Tests for OdysseyEngineeringTable.engineer_module_count() -- counts
distinct suit + weapon modules an engineer offers, from real JSON on
disk (tmp_path), not mocks."""
import json

from edc.core.odyssey_engineering import OdysseyEngineeringTable


def _write_fixture(tmp_path, suit_modules=None, weapon_modules=None):
    data = {
        "last_updated": "2026-08-13",
        "suit_modules": suit_modules or {},
        "weapon_modules": weapon_modules or {},
    }
    (tmp_path / "odyssey_engineering.json").write_text(json.dumps(data), encoding="utf-8")


def test_counts_one_suit_module(tmp_path):
    _write_fixture(tmp_path, suit_modules={
        "extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 1


def test_counts_one_weapon_module(tmp_path):
    _write_fixture(tmp_path, weapon_modules={
        "clean_shot": {"display_name": "Clean Shot", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 1


def test_suit_and_weapon_modules_combine(tmp_path):
    _write_fixture(
        tmp_path,
        suit_modules={"extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]}},
        weapon_modules={"clean_shot": {"display_name": "Clean Shot", "engineers": ["Yarden Bond"]}},
    )
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 2


def test_engineer_with_no_offerings_is_zero(tmp_path):
    _write_fixture(tmp_path, suit_modules={
        "extra_ammo": {"display_name": "Extra Ammo Capacity", "engineers": ["Yarden Bond"]},
    })
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Hero Ferrari") == 0


def test_no_data_file_returns_zero_for_everyone(tmp_path):
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 0
