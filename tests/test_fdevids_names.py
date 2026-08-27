"""FDevIDs symbol -> display-name table (ships)."""
from edc.core.fdevids_names import ShipNameTable


def _table(tmp_path):
    import shutil
    from pathlib import Path
    src = Path(__file__).parent.parent / "settings"
    dst = Path(tmp_path) / "settings"
    dst.mkdir(exist_ok=True)
    shutil.copy(src / "fdevids_ships.json", dst / "fdevids_ships.json")
    return ShipNameTable(dst)


def test_ship_display_name(tmp_path):
    ships = _table(tmp_path)
    assert ships.display_name("krait_mkii") == "Krait MkII"
    assert ships.display_name("sidewinder") == "Sidewinder"
    assert ships.display_name("does_not_exist") is None
    assert ships.display_name(None) is None


def test_reverse_lookup_by_display_name(tmp_path):
    ships = _table(tmp_path)
    assert ships.symbol_for_display("Krait MkII") == "krait_mkii"
    assert ships.symbol_for_display("krait_mkii") == "krait_mkii"
    assert ships.symbol_for_display("No Such Ship") is None


def test_search_finds_both_symbol_and_display(tmp_path):
    ships = _table(tmp_path)
    hits = ships.search_display("krait mkii")
    syms = [s for s, _ in hits]
    assert "krait_mkii" in syms
    hits2 = ships.search_display("krait_mkii")
    assert any(s.startswith("krait") for s, _ in hits2)
    assert ships.search_display("") == []
