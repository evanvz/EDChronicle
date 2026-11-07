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


def test_load_previous_wrong_shape_is_unreadable(tmp_path):
    for bad in ("[]", '{"findings": [{"area": "Other"}]}', '{"findings": "x"}'):
        (tmp_path / "app_status_2026-11-06.json").write_text(bad, encoding="utf-8")
        assert load_previous(tmp_path, "app_status_2026-11-07") == "unreadable"


def test_unknown_severity_sorts_last():
    md, _ = build_report(_results(_f("weird", "msg-w"), _f("start", "msg-s")), META, None, {})
    assert md.index("msg-s") < md.index("msg-w")


def test_journal_dir_read_does_not_rewrite_settings(tmp_path):
    from tools.app_status.report import _journal_dir
    settings = tmp_path / "settings" / "settings.json"
    settings.parent.mkdir()
    settings.write_bytes(b'{"journal_dir": "J:/x", "min_planet_value__100k": 3}')
    assert _journal_dir(tmp_path) == "J:/x"
    assert settings.read_bytes() == b'{"journal_dir": "J:/x", "min_planet_value__100k": 3}'
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "settings.json").write_bytes(b'{"journal_dir": "J:/y"}')
    assert _journal_dir(legacy) == "J:/y"
    assert not (legacy / "settings").exists()
    assert _journal_dir(tmp_path / "missing") is None


def test_main_with_list_previous_still_writes(tmp_path):
    jdir = tmp_path / "journals"
    write_synthetic_journal(jdir)
    (tmp_path / "app_status_2000-01-01.json").write_text("[]", encoding="utf-8")
    main(["--skip-tests", "--journal-dir", str(jdir)], app_dir=tmp_path, reports_dir=tmp_path)
    md = [p for p in tmp_path.glob("app_status_*.md")]
    assert len(md) == 1 and "previous report unreadable" in md[0].read_text(encoding="utf-8")


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
    assert any(f["severity"] == "info" and f["text"] == "tests skipped (--skip-tests)" for f in data["findings"])


def test_since_last_report_ignores_number_churn():
    prev = {"findings": [_f("replay", "edc.x: 12 errors, 3 tracebacks in 7 days (x4)")]}
    md, _ = build_report(_results(_f("replay", "edc.x: 15 errors, 0 tracebacks in 7 days")), META, prev, {})
    since = md.split("## Since last report")[1].split("## Mapping")[0]
    new, resolved = since.split("Resolved")
    assert "edc.x" not in new and "edc.x" not in resolved


def test_live_confirmed_non_dict_entry_is_tolerated(tmp_path, monkeypatch):
    from tools.app_status import report
    bad = tmp_path / "live.json"
    bad.write_text('{"Mining": "yes"}', encoding="utf-8")
    monkeypatch.setattr(report, "LIVE_CONFIRMED_PATH", bad)
    md, _ = build_report(_results(), META, None, {})
    assert "| Mining |" in md


def test_main_survives_malformed_json_files(tmp_path, monkeypatch):
    from tools.app_status import report
    live, areas = tmp_path / "live_confirmed.json", tmp_path / "areas.json"
    live.write_text("{bad", encoding="utf-8")
    areas.write_text("[1]", encoding="utf-8")
    monkeypatch.setattr(report, "LIVE_CONFIRMED_PATH", live)
    monkeypatch.setattr(report, "AREAS_PATH", areas)
    reports = tmp_path / "r"
    write_synthetic_journal(tmp_path / "j")
    main(["--skip-tests", "--journal-dir", str(tmp_path / "j")], app_dir=tmp_path, reports_dir=reports)
    data = json.loads(next(reports.glob("*.json")).read_text(encoding="utf-8"))
    starts = [f["text"] for f in data["findings"] if f["severity"] == "start"]
    assert any(t.startswith("live_confirmed.json unreadable") for t in starts)
    assert any(t.startswith("areas.json unreadable") for t in starts)


def test_all_journals_needs_full(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        main(["--all-journals", "--skip-tests"], app_dir=tmp_path, reports_dir=tmp_path)
    assert not list(tmp_path.glob("app_status_*"))


def _fake_child(monkeypatch, rc, out_text, stderr=b""):
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace

    def fake_run(cmd, **kw):
        if out_text is not None:
            Path(cmd[-1]).write_text(out_text, encoding="utf-8")
        return SimpleNamespace(returncode=rc, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_child_nonzero_exit_with_results_keeps_them(tmp_path, monkeypatch):
    from tools.app_status.report import _child
    _fake_child(monkeypatch, 3, json.dumps({"cells": {"Mining": "ok"}, "findings": [], "seconds": 1.0}))
    r = _child(tmp_path, "replay", {}, 10)
    assert r["cells"] == {"Mining": "ok"}
    assert [(f["severity"], f["text"]) for f in r["findings"]] == [("info", "child exited 3 after writing results")]


def test_child_crash_text_has_last_stderr_line(tmp_path, monkeypatch):
    from tools.app_status.report import _child
    _fake_child(monkeypatch, 1, None, b"Traceback\n  x\nValueError: boom\n")
    r = _child(tmp_path, "replay", {}, 10)
    assert r["findings"][0]["text"] == "check replay crashed (exit 1): ValueError: boom"
