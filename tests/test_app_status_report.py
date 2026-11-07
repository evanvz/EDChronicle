import json

from test_app_status_replay import write_synthetic_journal
from tools.app_status.report import build_report, exit_code, load_previous, main

META = {"date": "2026-11-07", "mode": "quick", "version": "1.0.3", "commit": "abc1234",
        "seconds": {}, "journal_window": "7 days", "replay_stats": {}}


def _f(severity, text="t", area="Other", check="x"):
    return {"area": area, "check": check, "severity": severity, "text": text}


def _results(*findings):
    return {"x": {"cells": {}, "findings": list(findings), "seconds": 0.0}}


def test_exit_code_only_fails_on_blocking_severities():
    _, js = build_report(_results(_f("suspect"), _f("info")), META, None, {})
    assert exit_code(js) == 0
    _, js = build_report(_results(_f("stale")), META, None, {})
    assert exit_code(js) == 1


def test_first_and_unreadable_previous():
    md, _ = build_report(_results(), META, None, {})
    assert "first report" in md
    md, _ = build_report(_results(), META, "unreadable", {})
    assert "previous report unreadable" in md


def test_since_last_report_new_and_resolved():
    prev = {"findings": [_f("suspect", "X (x3)")]}
    md, _ = build_report(_results(_f("suspect", "Y")), META, prev, {})
    since = md.split("## Since last report")[1].split("## Mapping")[0]
    new, resolved = since.split("Resolved")
    assert "Y" in new and "X" not in new
    assert "X" in resolved and "Y" not in resolved


def test_findings_ordered_by_severity():
    sevs = ["suspect", "stale", "replay", "test", "start"]
    md, _ = build_report(_results(*[_f(s, f"msg-{s}") for s in sevs]), META, None, {})
    attention = md.split("## Needs attention")[1].split("## Notes")[0]
    pos = [attention.index(f"msg-{s}") for s in ["start", "test", "replay", "stale", "suspect"]]
    assert pos == sorted(pos)


def test_load_previous_ignores_today_and_bad_json(tmp_path):
    assert load_previous(tmp_path, "app_status_2026-11-07") is None
    (tmp_path / "app_status_2026-11-05.json").write_text('{"findings": []}', encoding="utf-8")
    (tmp_path / "app_status_2026-11-07.json").write_text("{bad", encoding="utf-8")
    assert load_previous(tmp_path, "app_status_2026-11-07") == {"findings": []}
    (tmp_path / "app_status_2026-11-06.json").write_text("{bad", encoding="utf-8")
    assert load_previous(tmp_path, "app_status_2026-11-07") == "unreadable"


def test_main_writes_report_pair(tmp_path):
    jdir = tmp_path / "journals"
    write_synthetic_journal(jdir)
    code = main(["--skip-tests", "--journal-dir", str(jdir)], app_dir=tmp_path, reports_dir=tmp_path)
    md = list(tmp_path.glob("app_status_*.md"))
    js = list(tmp_path.glob("app_status_*.json"))
    assert len(md) == 1 and len(js) == 1
    data = json.loads(js[0].read_text(encoding="utf-8"))
    assert data["exit_code"] == code == 1
    assert any(f["text"] == "no database found" for f in data["findings"])
