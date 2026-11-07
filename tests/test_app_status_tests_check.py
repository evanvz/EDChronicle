from pathlib import Path
from tools.app_status.check_tests import (
    KNOWN_FAILURES, parse_junit, cells_from_counts, findings_from_junit, coverage_by_area)

AREAS = {"Overview/HUD": {"modules": ["edc/core/a.py"], "tests": ["tests/test_overview_*.py"]},
         "Mining": {"modules": ["edc/core/m.py"], "tests": ["tests/test_mining_*.py"]},
         "Other": {"modules": [], "tests": []}}

XML = """<?xml version="1.0"?><testsuites><testsuite>
<testcase classname="tests.test_overview_x" name="test_ok"/>
<testcase classname="tests.test_overview_x" name="test_bad"><failure message="boom&#10;second line">tb</failure></testcase>
<testcase classname="tests.test_overview_x.TestC" name="test_skip"><skipped message="s"/></testcase>
</testsuite></testsuites>"""


def _xml(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text(XML, encoding="utf-8")
    return p


def test_parse_junit(tmp_path):
    assert parse_junit(_xml(tmp_path)) == {"tests/test_overview_x.py": {"passed": 1, "failed": 1, "errors": 0}}


def test_cells(tmp_path):
    counts = parse_junit(_xml(tmp_path))
    cells = cells_from_counts(counts, AREAS, {})
    assert cells["Overview/HUD"] == "fail 1/2" and cells["Mining"] == "none"
    assert cells_from_counts(counts, AREAS, {"tests/test_overview_x.py": 1})["Overview/HUD"] == "pass 2 (+1 known)"


def test_findings_and_known(tmp_path):
    f, known = findings_from_junit(_xml(tmp_path), AREAS, set())
    assert [(x["severity"], x["text"]) for x in f] == [("test", "tests/test_overview_x.py::test_bad: boom")]
    f, known = findings_from_junit(_xml(tmp_path), AREAS, {"tests/test_overview_x.py::test_bad"})
    assert f[0]["severity"] == "info" and known == {"tests/test_overview_x.py": 1}


def test_known_failures_ids():
    assert "tests/test_eddatahub_ticks.py::test_hub_ticks_parsed_and_offline_is_none" in KNOWN_FAILURES
    assert len(KNOWN_FAILURES) == 2


def test_coverage_by_area():
    cov = {"files": {r"edc\core\a.py": {"summary": {"covered_lines": 1, "num_statements": 4}},
                     "edc/core/zz.py": {"summary": {"covered_lines": 3, "num_statements": 4}}}}
    out = coverage_by_area(cov, AREAS)
    assert out["Overview/HUD"] == 25.0 and out["Other"] == 75.0 and "Mining" not in out
