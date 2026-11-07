"""Run one window-building check in its own process (a second MainWindow in one process segfaults).
Usage: python -m tools.app_status.child <check-name> <args.json> <out.json>"""
import json
import os
import sys
from pathlib import Path


def _safe(o):
    return sorted(o, key=str) if isinstance(o, (set, frozenset)) else str(o)


def run(name: str, args: dict) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    repo_root = Path(args["repo_root"])
    if name == "app_start":
        from tools.app_status.sandbox import check_app_start
        return check_app_start(repo_root)
    if name == "replay":
        from tools.app_status.replay import run_replay
        keep = args.get("keep_db")
        return run_replay(repo_root, args["journal_dir"], args["days"], Path(keep) if keep else None)
    if name == "importer":
        from tools.app_status.importer_compare import compare_paths
        return compare_paths(repo_root, args["journal_dir"], args["days"], Path(args["live_db"]))
    raise SystemExit(f"unknown check {name}")


if __name__ == "__main__":
    name, args_path, out_path = sys.argv[1:4]
    result = run(name, json.loads(Path(args_path).read_text(encoding="utf-8")))
    Path(out_path).write_text(json.dumps(result, default=_safe), encoding="utf-8")
