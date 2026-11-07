from tools.app_status import code_health as ch


def test_parse_vulture_two_lines():
    text = ("edc\\app.py:41: unused variable 'context' (100% confidence)\n"
            "edc\\audio\\x.py:146: unused import '_time' (90% confidence)\n")
    r = ch.parse_vulture(text)
    assert r == [("edc/app.py", 41, "unused variable 'context' (100% confidence)"),
                 ("edc/audio/x.py", 146, "unused import '_time' (90% confidence)")]


def test_parse_ruff_json():
    t = '[{"code":"F401","filename":"C:\\\\r\\\\edc\\\\a.py","location":{"row":3,"column":1}}]'
    assert ch.parse_ruff_json(t) == [("C:/r/edc/a.py", 3, "F401")]


def test_dual_path_events():
    assert ch.dual_path_events('if name == "Scan": ...\n"Docked"', ['if name == "Scan":']) == ["Scan"]


def test_missing_tool_is_info_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "_run", lambda *a, **k: (None, "vulture not installed (pip install -r requirements-dev.txt)"))
    r = ch.check_code_health(tmp_path, None)
    assert any("vulture not installed" in f["text"] for f in r["findings"])
    assert all(f["severity"] == "info" for f in r["findings"])


def test_cap_adds_summary(monkeypatch, tmp_path):
    lines = "".join(f"edc\\app.py:{i}: unused variable 'v{i}' (60% confidence)\n" for i in range(60))
    monkeypatch.setattr(ch, "_run", lambda r, m, a: (lines, None) if m == "vulture" else ("[]" if m == "ruff" else "", None))
    r = ch.check_code_health(tmp_path, {"Other": 50.0})
    texts = [f["text"] for f in r["findings"]]
    assert "vulture: 60 unused? (first 50 listed)" in texts
    assert sum(t.startswith("unused?") for t in texts) == 50
