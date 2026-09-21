"""CommodityCategoryTable (settings loader) -- commodity symbol -> Frontier's
own category + display name, sourced from EDCD/FDevIDs commodity.csv."""
import json

from edc.core.commodity_categories import CommodityCategoryTable


def test_loads_category_and_name_from_settings_json(tmp_path):
    (tmp_path / "commodity_categories.json").write_text(
        json.dumps({"commodities": {"aluminium": {"name": "Aluminium", "category": "Metals"}}}),
        encoding="utf-8",
    )
    table = CommodityCategoryTable(tmp_path)
    assert table.category_for("aluminium") == "Metals"
    assert table.display_name_for("aluminium") == "Aluminium"
    assert table.category_for("ALUMINIUM") == "Metals"  # case-insensitive


def test_unknown_commodity_returns_none(tmp_path):
    (tmp_path / "commodity_categories.json").write_text(
        json.dumps({"commodities": {"aluminium": {"name": "Aluminium", "category": "Metals"}}}),
        encoding="utf-8",
    )
    table = CommodityCategoryTable(tmp_path)
    assert table.category_for("unobtainium") is None
    assert table.display_name_for("unobtainium") is None


def test_missing_file_returns_none_not_an_error(tmp_path):
    table = CommodityCategoryTable(tmp_path)
    assert table.category_for("aluminium") is None
    assert table.display_name_for("aluminium") is None


def test_malformed_json_returns_none_not_an_error(tmp_path):
    (tmp_path / "commodity_categories.json").write_text("not valid json", encoding="utf-8")
    table = CommodityCategoryTable(tmp_path)
    assert table.category_for("aluminium") is None


def test_real_settings_file_covers_colonisation_commodities():
    from pathlib import Path
    table = CommodityCategoryTable(Path(__file__).resolve().parents[1] / "settings")
    assert table.category_for("aluminium") == "Metals"
    assert table.category_for("water") == "Chemicals"
    assert table.category_for("cmmcomposite") == "Industrial Materials"
    assert table.display_name_for("cmmcomposite") == "CMM Composite"
    assert table.display_name_for("liquidoxygen") == "Liquid oxygen"
