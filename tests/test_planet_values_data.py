"""settings/planet_values.json mapped columns include the Odyssey mapping bonus
(MattG's formula, recomputed 2026-10-14); unmapped columns were already right."""
from pathlib import Path

from edc.core.planet_values import PlanetValueTable

TABLE = PlanetValueTable.load_from_paths(Path(__file__).resolve().parents[1] / "settings" / "planet_values.json")


def test_earthlike_values():
    assert TABLE.estimate("Earthlike body", False, mapped=False, first_discovered=False) == 270_290
    assert TABLE.estimate("Earthlike body", False, mapped=True, first_discovered=False) == 1_464_068
    assert TABLE.estimate("Earthlike body", False, mapped=False, first_discovered=True) == 702_753
    assert TABLE.estimate("Earthlike body", False, mapped=True, first_discovered=True) == 4_224_870


def test_small_body_floor():
    assert TABLE.estimate("Icy body", False, mapped=True, first_discovered=False) == 2_777
