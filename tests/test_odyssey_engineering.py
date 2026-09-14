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


# --- materials_usage_index() -- reverse lookup for the Materials tab's
# ShipLocker storage detail dialog: "what is this loot item actually for?" ---

def _write_full_fixture(tmp_path, suits=None, weapons=None, suit_modules=None, weapon_modules=None):
    data = {
        "last_updated": "2026-08-13",
        "suits": suits or {},
        "weapons": weapons or {},
        "suit_modules": suit_modules or {},
        "weapon_modules": weapon_modules or {},
    }
    (tmp_path / "odyssey_engineering.json").write_text(json.dumps(data), encoding="utf-8")


def test_suit_module_material_maps_to_display_name(tmp_path):
    _write_full_fixture(tmp_path, suit_modules={
        "enhanced_tracking": {"display_name": "Enhanced Tracking", "materials": {"circuitboard": 3}},
    })
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert index["circuitboard"] == ["Enhanced Tracking (Suit Mod)"]


def test_weapon_module_material_maps_to_display_name(tmp_path):
    _write_full_fixture(tmp_path, weapon_modules={
        "greater_range_laser": {"display_name": "Greater Range Laser", "materials": {"microtransformer": 8}},
    })
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert index["microtransformer"] == ["Greater Range Laser (Weapon Mod)"]


def test_suit_grade_upgrade_material_included_per_grade(tmp_path):
    _write_full_fixture(tmp_path, suits={
        "Maverick": {"2": {"graphene": 2}, "3": {"graphene": 5}},
    })
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert index["graphene"] == ["Maverick Suit — Grade 2", "Maverick Suit — Grade 3"]


def test_weapon_grade_upgrade_material_included(tmp_path):
    _write_full_fixture(tmp_path, weapons={"TK": {"2": {"microelectrode": 1}}})
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert index["microelectrode"] == ["TK Weapon — Grade 2"]


def test_material_used_by_multiple_things_lists_all_without_duplicates(tmp_path):
    _write_full_fixture(
        tmp_path,
        suit_modules={
            "audio_masking": {"display_name": "Audio Masking", "materials": {"circuitboard": 3}},
            "stowed_reloading": {"display_name": "Stowed Reloading", "materials": {"circuitboard": 3}},
        },
    )
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert index["circuitboard"] == ["Audio Masking (Suit Mod)", "Stowed Reloading (Suit Mod)"]


def test_material_with_no_known_use_is_absent_from_index(tmp_path):
    _write_full_fixture(tmp_path, suit_modules={
        "enhanced_tracking": {"display_name": "Enhanced Tracking", "materials": {"circuitboard": 3}},
    })
    table = OdysseyEngineeringTable(tmp_path)
    index = table.materials_usage_index()
    assert "healthpack" not in index


def test_no_data_file_returns_zero_for_everyone(tmp_path):
    table = OdysseyEngineeringTable(tmp_path)
    assert table.engineer_module_count("Yarden Bond") == 0
