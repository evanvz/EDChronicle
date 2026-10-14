"""settings/exo_values.json keys must be the game's own Species_Localised names (the
lookup is exact), with values fact-checked 2026-10-14 against EDMC-BioScan, the ED wiki
and real SellOrganicData payouts."""
from pathlib import Path

from edc.core.exo_values import ExoValueTable

TABLE = ExoValueTable.load_from_paths(Path(__file__).resolve().parents[1] / "settings" / "exo_values.json")


def test_journal_names_resolve():
    # names exactly as SellOrganicData / ScanOrganic write them
    assert TABLE.get_value("Lividum Brain Tree") == 1_593_700
    assert TABLE.get_value("Roseum Brain Tree") == 1_593_700
    assert TABLE.get_value("Thargoid Spires") == 2_247_100


def test_values_confirmed_by_real_payouts():
    assert TABLE.get_value("Fonticulua Fluctus") == 20_000_000
    assert TABLE.get_value("Tussock Ventusa") == 3_227_700
    assert TABLE.get_value("Bacterium Nebulus") == 5_289_900
