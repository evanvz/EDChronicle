import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.app_status.areas import AREAS_PATH, AREA_ORDER, area_of, load_json

KNOWN_FAILURES = {
    "tests/test_eddatahub_ticks.py::test_hub_ticks_parsed_and_offline_is_none",
    "tests/test_expansion_forecast_repo.py::test_presence_has_first_and_latest_reading",
}
TIMEOUT_S = 1800


def _cases(xml_path):
    """Yield (file, nodeid, status, message); status is passed/failed/errors/skipped."""
    for tc in ET.parse(xml_path).getroot().iter("testcase"):
        parts = tc.get("classname", "").split(".")
        i = next((n for n, p in enumerate(parts) if p.startswith("test_")), None)
        if i is None:
            continue
        file = "/".join(parts[:i + 1]) + ".py"
        nodeid = "::".join([file] + parts[i + 1:] + [tc.get("name", "")])
        bad = tc.find("failure")
        status, msg = ("failed", None) if bad is not None else ("passed", None)
        if bad is None:
            bad = tc.find("error")
            status = "errors" if bad is not None else status
        if bad is not None:
            msg = (bad.get("message") or bad.text or "").strip().splitlines()
            msg = msg[0] if msg else ""
        elif tc.find("skipped") is not None:
            status = "skipped"
        yield file, nodeid, status, msg


def parse_junit(xml_path):
    counts = {}
    for file, _, status, _ in _cases(xml_path):
        if status != "skipped":
            c = counts.setdefault(file, {"passed": 0, "failed": 0, "errors": 0})
            c[status] += 1
    return counts


def cells_from_counts(counts, areas, known_failed):
    tot = {a: [0, 0, 0] for a in areas}  # total, failures, known
    for file, c in counts.items():
        t = tot[area_of(file, "test", areas)]
        t[0] += c["passed"] + c["failed"] + c["errors"]
        t[1] += c["failed"] + c["errors"] - known_failed.get(file, 0)
        t[2] += known_failed.get(file, 0)
    cells = {}
    for a, (n, f, k) in tot.items():
        cells[a] = "none" if not n else f"fail {f}/{n}" if f else f"pass {n}" + (f" (+{k} known)" if k else "")
    return cells


def findings_from_junit(xml_path, areas, known):
    findings, known_failed = [], {}
    for file, nodeid, status, msg in _cases(xml_path):
        if status not in ("failed", "errors"):
            continue
        is_known = nodeid in known
        if is_known:
            known_failed[file] = known_failed.get(file, 0) + 1
        findings.append({"area": area_of(file, "test", areas), "check": "tests",
                         "severity": "info" if is_known else "test", "text": f"{nodeid}: {msg}"})
    return findings, known_failed


def coverage_by_area(cov, areas):
    tot = {}
    for path, f in cov["files"].items():
        t = tot.setdefault(area_of(path.replace("\\", "/"), "module", areas), [0, 0])
        t[0] += f["summary"]["covered_lines"]
        t[1] += f["summary"]["num_statements"]
    return {a: round(100 * c / n, 1) for a, (c, n) in tot.items() if n}


def run_tests(repo_root, full):
    start = time.time()
    areas = load_json(AREAS_PATH)
    result = {"cells": {}, "findings": [], "seconds": 0.0}

    def fail(text):
        result["findings"].append({"area": "Other", "check": "tests", "severity": "test", "text": text})
        result["seconds"] = round(time.time() - start, 1)
        return result

    with tempfile.TemporaryDirectory() as tmp:
        junit, covjson = Path(tmp) / "j.xml", Path(tmp) / "cov.json"
        cmd = [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
        if full:
            cmd += ["--cov=edc", "--cov=persistence", f"--cov-report=json:{covjson}"]
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        try:
            subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return fail(f"pytest timed out after {TIMEOUT_S}s")
        if not junit.exists():
            return fail("pytest produced no junit XML")
        result["findings"], known_failed = findings_from_junit(junit, areas, KNOWN_FAILURES)
        result["cells"] = cells_from_counts(parse_junit(junit), areas, known_failed)
        if full and covjson.exists():
            result["coverage"] = coverage_by_area(load_json(covjson), areas)
    result["seconds"] = round(time.time() - start, 1)
    return result
