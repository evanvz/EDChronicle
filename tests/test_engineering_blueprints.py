"""Tests for EngineeringBlueprintTable.engineer_blueprint_count() -- counts
distinct blueprints an engineer offers at any grade, from real JSON on
disk (tmp_path), not mocks."""
import json

from edc.core.engineering_blueprints import EngineeringBlueprintTable


def _write_fixture(tmp_path, blueprints):
    data = {"last_updated": "2026-08-13", "blueprints": blueprints}
    (tmp_path / "engineering_blueprints.json").write_text(json.dumps(data), encoding="utf-8")


def test_counts_one_blueprint_offered_at_one_grade(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 1


def test_same_blueprint_at_multiple_grades_counts_once(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}, "2": {}, "3": {}},
            "grade_engineers": {
                "1": ["Felicity Farseer"],
                "2": ["Felicity Farseer"],
                "3": ["Felicity Farseer"],
            },
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 1


def test_counts_multiple_distinct_blueprints(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
        "armour_heavy": {
            "display_name": "Heavy Duty Armour",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 2


def test_engineer_with_no_offerings_is_zero(tmp_path):
    _write_fixture(tmp_path, {
        "fsd_range": {
            "display_name": "FSD Range",
            "grades": {"1": {}},
            "grade_engineers": {"1": ["Felicity Farseer"]},
        },
    })
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("The Dweller") == 0


def test_no_data_file_returns_zero_for_everyone(tmp_path):
    table = EngineeringBlueprintTable(tmp_path)
    assert table.engineer_blueprint_count("Felicity Farseer") == 0
