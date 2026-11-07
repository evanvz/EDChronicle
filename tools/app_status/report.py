import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.app_status.areas import AREA_ORDER, AREAS_PATH, LIVE_CONFIRMED_PATH, load_json, mapping_problems

SEVERITIES = ["start", "test", "replay", "stale", "suspect", "info"]
BLOCKING = {"start", "test", "replay", "stale"}
REPO_ROOT = Path(__file__).resolve().parents[2]
_XN = re.compile(r" \(x\d+\)$")


def exit_code(report_json: dict) -> int:
    return int(any(f["severity"] in BLOCKING for f in report_json["findings"]))


def load_previous(reports_dir: Path, today_stem: str) -> dict | None | str:
    older = sorted(p for p in Path(reports_dir).glob("app_status_*.json") if p.stem < today_stem)
    if not older:
        return None
    try:
        return json.loads(older[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"


def _key(f):
    return f["area"], f["check"], _XN.sub("", f["text"])


def _line(f):
    return f"- [{f['severity']}] {f['area']}: {f['text']}"


def _cell(results, check, area):
    return (results.get(check) or {}).get("cells", {}).get(area, "—")


def build_report(results: dict, meta: dict, previous, problems: dict) -> tuple[str, dict]:
    findings = [f for r in results.values() for f in r.get("findings", [])]
    order = {a: i for i, a in enumerate(AREA_ORDER)}
    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), order.get(f["area"], len(order))))
    js = {"meta": meta, "results": results, "problems": problems, "findings": findings}
    js["exit_code"] = exit_code(js)
    must = sum(f["severity"] in BLOCKING for f in findings)
    live = load_json(LIVE_CONFIRMED_PATH)
    full = meta["mode"] == "full"

    secs = ", ".join(f"{k} {v:.0f}s" for k, v in meta["seconds"].items())
    stats = meta.get("replay_stats") or {}
    md = [f"# App Status Report — {meta['date']} ({meta['mode']})", "",
          f"Version {meta['version']} · commit {meta['commit']} · journals: {meta['journal_window']}"
          f" ({stats.get('files', 0)} files, {stats.get('events', 0)} events) · {secs}", "",
          f"**Result: FAIL ({must} must-fix)**" if must else "**Result: PASS**", ""]
    starts = [f for f in findings if f["check"] in ("app start", "app_start") and f["severity"] == "start"]
    md += [f"App start: {f'{len(starts)} errors' if starts else 'ok'}"
           if "app_start" in results else "App start: not run", ""]

    md += ["| Area | Tests | Replay | Data fresh | Code health | Last live-confirmed |",
           "|---|---|---|---|---|---|"]
    for a in AREA_ORDER:
        lc = live.get(a) or {}
        conf = (lc.get("date") or "never") + (f" ({lc['note']})" if lc.get("note") else "")
        health = f"{_cell(results, 'code_health', a)}; {_cell(results, 'importer', a)}" if full else "—"
        md.append(f"| {a} | {_cell(results, 'tests', a)} | {_cell(results, 'replay', a)}; "
                  f"{_cell(results, 'logs', a)} | {_cell(results, 'freshness', a)} | {health} | {conf} |")

    md += ["", "## Needs attention", ""]
    md += [_line(f) for f in findings if f["severity"] != "info"] or ["none"]
    md += ["", "## Notes", ""]
    md += [_line(f) for f in findings if f["severity"] == "info"] or ["none"]

    md += ["", "## Since last report", ""]
    if previous is None:
        md.append("first report")
    elif previous == "unreadable":
        md.append("previous report unreadable")
    else:
        old = {_key(f): f for f in previous.get("findings", [])}
        cur = {_key(f): f for f in findings}
        md += ["New:"] + ([_line(f) for k, f in cur.items() if k not in old] or ["none"])
        md += ["", "Resolved:"] + ([_line(f) for k, f in old.items() if k not in cur] or ["none"])

    md += ["", "## Mapping", ""]
    bad = [f"- unmapped: {p}" for p in problems.get("unmapped", [])]
    bad += [f"- ambiguous: {p}" for p in problems.get("ambiguous", [])]
    md += bad or ["ok"]
    return "\n".join(md) + "\n", js


def _crash(name, text):
    sev = {"app_start": "start", "tests": "test"}.get(name, "replay")
    return {"cells": {}, "seconds": 0.0, "findings": [{"area": "Other", "check": name, "severity": sev, "text": text}]}


def _child(repo_root, name, args, timeout):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        a, out = Path(tmp) / "args.json", Path(tmp) / "out.json"
        a.write_text(json.dumps({"repo_root": str(repo_root), **args}), encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, "-m", "tools.app_status.child", name, str(a), str(out)],
                               cwd=repo_root, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return _crash(name, f"check {name} timed out")
        if p.returncode or not out.exists():
            return _crash(name, f"check {name} crashed (exit {p.returncode})")
        return json.loads(out.read_text(encoding="utf-8"))


def _commit(repo_root):
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root,
                           capture_output=True, text=True, timeout=30)
        return p.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv: list[str], repo_root: Path | None = None, app_dir: Path | None = None,
         reports_dir: Path | None = None) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    ap = argparse.ArgumentParser(prog="python -m tools.app_status")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--all-journals", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--journal-dir")
    args = ap.parse_args(argv)

    from edc.config import ConfigStore, default_app_dir
    from edc.version import APP_VERSION
    repo_root = Path(repo_root or REPO_ROOT)
    app_dir = Path(app_dir or ConfigStore(default_app_dir()).app_dir)
    reports_dir = Path(reports_dir or repo_root / "reports")
    journal_dir = args.journal_dir or ConfigStore(app_dir).load().journal_dir
    full = args.full
    days = (None if args.all_journals else 30) if full else 7
    timeout = 1800 if full else 600
    now = datetime.now(timezone.utc)
    areas = load_json(AREAS_PATH)
    results, seconds, problems = {}, {}, {}

    def timed(name, fn):
        t = time.time()
        try:
            results[name] = fn()
        except Exception as e:
            results[name] = _crash(name, f"check {name} crashed: {e}")
        seconds[name] = round(time.time() - t, 1)

    from tools.app_status import code_health, freshness
    from tools.app_status.check_tests import run_tests
    if not args.skip_tests:
        timed("tests", lambda: run_tests(repo_root, full))
    timed("app_start", lambda: _child(repo_root, "app_start", {}, 600))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        live_db = Path(tmp) / "live.db"
        timed("replay", lambda: _child(repo_root, "replay", {"journal_dir": journal_dir, "days": days,
                                                             "keep_db": str(live_db)}, timeout))
        if full and live_db.exists():
            timed("importer", lambda: _child(repo_root, "importer", {"journal_dir": journal_dir, "days": days,
                                                                     "live_db": str(live_db)}, timeout))
    timed("freshness", lambda: freshness.run_freshness(app_dir / "data" / "edhelper.db", journal_dir, areas, now))
    timed("logs", lambda: freshness.scan_logs(app_dir / "logs", 7, areas, now))
    if full:
        cov = (results.get("tests") or {}).get("coverage")
        timed("code_health", lambda: code_health.check_code_health(repo_root, cov))
    try:
        problems = mapping_problems(repo_root, areas)
    except Exception as e:
        results["mapping"] = _crash("mapping", f"check mapping crashed: {e}")

    date = datetime.now().strftime("%Y-%m-%d")
    stem = f"app_status_{date}"
    meta = {"date": date, "mode": "full" if full else "quick", "version": APP_VERSION,
            "commit": _commit(repo_root), "seconds": seconds,
            "journal_window": "all" if days is None else f"{days} days", "journal_dir": journal_dir,
            "replay_stats": (results.get("replay") or {}).get("stats", {})}
    md, js = build_report(results, meta, load_previous(reports_dir, stem), problems)
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"{stem}.md"
    md_path.write_text(md, encoding="utf-8")
    (reports_dir / f"{stem}.json").write_text(json.dumps(js, indent=1, default=str), encoding="utf-8")
    print(md_path)
    print(next(line for line in md.splitlines() if line.startswith("**Result")))
    return js["exit_code"]
