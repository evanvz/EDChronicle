"""FDevIDs symbol -> display-name tables (modules + ships)."""
from edc.core.fdevids_names import ModuleNameTable, ShipNameTable


def _tables(tmp_path):
    import shutil
    from pathlib import Path
    src = Path(__file__).parent.parent / "settings"
    dst = Path(tmp_path) / "settings"
    dst.mkdir(exist_ok=True)
    for name in ("fdevids_modules.json", "fdevids_ships.json"):
        shutil.copy(src / name, dst / name)
    return ModuleNameTable(dst), ShipNameTable(dst)


def test_module_display_name(tmp_path):
    mods, _ = _tables(tmp_path)
    assert mods.display_name("int_shieldgenerator_size3_class3") == "Shield Generator"
    assert mods.display_name("HPT_PulseLaser_Fixed_Small") == "Pulse Laser"
    assert mods.display_name("does_not_exist") is None
    assert mods.display_name(None) is None


def test_ship_display_name(tmp_path):
    _, ships = _tables(tmp_path)
    assert ships.display_name("krait_mkii") == "Krait MkII"
    assert ships.display_name("sidewinder") == "Sidewinder"


def test_reverse_lookup_by_display_name(tmp_path):
    _, ships = _tables(tmp_path)
    assert ships.symbol_for_display("Krait MkII") == "krait_mkii"
    assert ships.symbol_for_display("krait_mkii") == "krait_mkii"
    assert ships.symbol_for_display("No Such Ship") is None


def test_search_finds_both_symbol_and_display(tmp_path):
    mods, _ = _tables(tmp_path)
    hits = mods.search_display("shield generator")
    syms = [s for s, _ in hits]
    assert "int_shieldgenerator_size3_class3" in syms
    hits2 = mods.search_display("shieldgenerator")
    assert any(s.startswith("int_shieldgenerator") for s, _ in hits2)
    assert mods.search_display("") == []
