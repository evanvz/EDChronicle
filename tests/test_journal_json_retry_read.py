"""MainWindow._read_journal_json_with_retry() -- Cargo.json/ShipLocker.json
are truncated then rewritten by the game, so a read can land on an empty
file mid-write. Retries a couple times on empty before giving up (live
error observed: JSONDecodeError on an empty ShipLocker.json read)."""
import json
import time

from edc.ui.main_window import MainWindow


def test_reads_normally_when_file_has_content(tmp_path):
    path = tmp_path / "Cargo.json"
    path.write_text(json.dumps({"Inventory": [1, 2, 3]}), encoding="utf-8")
    assert MainWindow._read_journal_json_with_retry(path) == {"Inventory": [1, 2, 3]}


def test_retries_past_a_transient_empty_read(tmp_path, monkeypatch):
    path = tmp_path / "ShipLocker.json"
    path.write_text("", encoding="utf-8")

    real_read_text = type(path).read_text
    calls = {"n": 0}

    def flaky_read_text(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ""
        return json.dumps({"Items": []})

    monkeypatch.setattr(type(path), "read_text", flaky_read_text)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    result = MainWindow._read_journal_json_with_retry(path)
    assert result == {"Items": []}
    assert calls["n"] == 2


def test_raises_if_still_empty_after_retries(tmp_path, monkeypatch):
    path = tmp_path / "Cargo.json"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(time, "sleep", lambda _: None)

    try:
        MainWindow._read_journal_json_with_retry(path)
        assert False, "expected JSONDecodeError"
    except json.JSONDecodeError:
        pass
