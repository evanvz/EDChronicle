"""GuardianTechnologyBrokerTable (settings loader) -- offline advisory
recipe reference for Guardian Technology Broker unlocks, mirroring
OdysseyEngineeringTable's loader shape."""
import json

from edc.core.guardian_technology_broker import GuardianTechnologyBrokerTable


def test_loads_unlocks_from_settings_json(tmp_path):
    (tmp_path / "guardian_technology_broker.json").write_text(
        json.dumps({
            "last_updated": "2026-09-21",
            "unlocks": {
                "Guardian FSD Booster": {
                    "ingredients": [
                        {"symbol": "guardian_powercell", "display_name": "Guardian Power Cell",
                         "kind": "material", "quantity": 21},
                        {"symbol": "hnshockmount", "display_name": "HN Shock Mount",
                         "kind": "commodity", "quantity": 8},
                    ]
                }
            },
        }),
        encoding="utf-8",
    )
    table = GuardianTechnologyBrokerTable(tmp_path)
    assert table.has_data() is True
    assert table.unlock_names() == ["Guardian FSD Booster"]
    ingredients = table.ingredients("Guardian FSD Booster")
    assert len(ingredients) == 2
    assert ingredients[0]["symbol"] == "guardian_powercell"
    assert ingredients[0]["kind"] == "material"
    assert ingredients[1]["kind"] == "commodity"


def test_missing_file_returns_empty_not_an_error(tmp_path):
    table = GuardianTechnologyBrokerTable(tmp_path)
    assert table.has_data() is False
    assert table.unlock_names() == []
    assert table.ingredients("Anything") == []


def test_malformed_json_returns_empty_not_an_error(tmp_path):
    (tmp_path / "guardian_technology_broker.json").write_text("not valid json", encoding="utf-8")
    table = GuardianTechnologyBrokerTable(tmp_path)
    assert table.has_data() is False


def test_real_settings_file_has_29_unlocks():
    """Guards against a data-file regression -- 29 is the confirmed count
    of Type=="Guardian"/Engineers==["@Technology"] recipes ported from
    msarilar/EDEngineer."""
    from pathlib import Path
    table = GuardianTechnologyBrokerTable(Path(__file__).resolve().parents[1] / "settings")
    names = table.unlock_names()
    assert len(names) == 29
    for name in names:
        ingredients = table.ingredients(name)
        assert len(ingredients) > 0
        for ing in ingredients:
            assert ing["kind"] in ("material", "commodity")
            assert ing["quantity"] > 0
            assert ing["symbol"]
