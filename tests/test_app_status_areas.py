from pathlib import Path
from tools.app_status.areas import AREAS_PATH, AREA_ORDER, area_of, load_json, mapping_problems

ROOT = Path(__file__).parent.parent

def test_unknown_module_falls_to_other():
    assert area_of("edc/core/nope_xyz.py", "module", {"A": {"modules": ["edc/ui/*"], "tests": []}}) == "Other"

def test_first_matching_area_wins():
    areas = {"A": {"modules": ["edc/core/exo_*.py"], "tests": []}, "B": {"modules": ["edc/core/*"], "tests": []}}
    assert area_of("edc/core/exo_predictor.py", "module", areas) == "A"

def test_real_map_has_no_gaps_or_overlaps():
    probs = mapping_problems(ROOT, load_json(AREAS_PATH))
    assert probs == {"unmapped": [], "ambiguous": []}

def test_area_order_matches_map_and_ends_with_other():
    assert AREA_ORDER[-1] == "Other" and set(AREA_ORDER) == set(load_json(AREAS_PATH))

def test_reports_dir_is_ignored():
    assert "reports/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
