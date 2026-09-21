"""ShipPadSizeTable (settings loader) -- ship internal symbol -> max
landing pad size, sourced from EDCD/coriolis-data's per-ship class field."""
import json

from edc.core.ship_pad_sizes import ShipPadSizeTable


def test_loads_pad_sizes_from_settings_json(tmp_path):
    (tmp_path / "ship_pad_sizes.json").write_text(
        json.dumps({"pad_sizes": {"anaconda": "L", "viper": "S"}}),
        encoding="utf-8",
    )
    table = ShipPadSizeTable(tmp_path)
    assert table.pad_size_for("anaconda") == "L"
    assert table.pad_size_for("viper") == "S"
    assert table.pad_size_for("ANACONDA") == "L"  # case-insensitive


def test_unknown_ship_returns_none(tmp_path):
    (tmp_path / "ship_pad_sizes.json").write_text(
        json.dumps({"pad_sizes": {"anaconda": "L"}}), encoding="utf-8",
    )
    table = ShipPadSizeTable(tmp_path)
    assert table.pad_size_for("mediumtransport01") is None
    assert table.pad_size_for(None) is None
    assert table.pad_size_for("") is None


def test_missing_file_returns_none_not_an_error(tmp_path):
    table = ShipPadSizeTable(tmp_path)
    assert table.pad_size_for("anaconda") is None


def test_malformed_json_returns_none_not_an_error(tmp_path):
    (tmp_path / "ship_pad_sizes.json").write_text("not valid json", encoding="utf-8")
    table = ShipPadSizeTable(tmp_path)
    assert table.pad_size_for("anaconda") is None


def test_real_settings_file_covers_common_ships():
    from pathlib import Path
    table = ShipPadSizeTable(Path(__file__).resolve().parents[1] / "settings")
    assert table.pad_size_for("sidewinder") == "S"
    assert table.pad_size_for("python") == "M"
    assert table.pad_size_for("anaconda") == "L"
    assert table.pad_size_for("cutter") == "L"
    assert table.pad_size_for("type9") == "L"
