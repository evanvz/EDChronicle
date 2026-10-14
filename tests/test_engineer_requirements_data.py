"""settings/engineer_requirements.json, fact-checked 2026-10-14 against the ED wiki;
commodity names must match the game's (EDCD FDevIDs)."""
from pathlib import Path

from edc.core.engineering_blueprints import EngineeringBlueprintTable

TABLE = EngineeringBlueprintTable(Path(__file__).resolve().parents[1] / "settings")


def test_all_engineers_present():
    assert len(TABLE.all_engineer_requirements()) == 38


def test_game_commodity_names():
    assert "Xihe Biomorphic Companions" in TABLE.engineer_requirements("Zacariah Nemo")["unlock"]
