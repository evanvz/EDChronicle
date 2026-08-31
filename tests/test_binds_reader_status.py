"""Tests for binds_reader.get_binds_status() -- real temp-dir fixtures, not
mocks, since the logic is pure filesystem reads (StartPreset.4.start plus
matching .binds file lookup)."""
import edc.core.binds_reader as binds_reader_mod
from edc.core.binds_reader import get_binds_status

_MINIMAL_BINDS_XML = '<?xml version="1.0" encoding="UTF-8" ?><Root MajorVersion="4" MinorVersion="2"></Root>'


def test_no_bindings_dir(monkeypatch):
    monkeypatch.setattr(binds_reader_mod, "_find_bindings_dir", lambda: None)
    status = get_binds_status(None)
    assert status["bindings_dir"] is None
    assert status["binds_file"] is None
    assert status["mismatch"] is False


def test_no_start_file_defaults_to_custom(tmp_path):
    (tmp_path / "Custom.4.2.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    status = get_binds_status(tmp_path)
    assert status["resolved_preset"] == "Custom"
    assert status["binds_file"] == "Custom.4.2.binds"
    assert status["preset_lines"] == []
    assert status["mismatch"] is False


def test_all_four_slots_agree_no_mismatch(tmp_path):
    (tmp_path / "StartPreset.4.start").write_text("Custom\nCustom\nCustom\nCustom\n", encoding="utf-8")
    (tmp_path / "Custom.4.4.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    status = get_binds_status(tmp_path)
    assert status["resolved_preset"] == "Custom"
    assert status["binds_file"] == "Custom.4.4.binds"
    assert status["preset_lines"] == ["Custom", "Custom", "Custom", "Custom"]
    assert status["mismatch"] is False


def test_mismatched_slots_detected(tmp_path):
    (tmp_path / "StartPreset.4.start").write_text("Custom\nCustom\nCustom\nConsoleX360\n", encoding="utf-8")
    (tmp_path / "Custom.4.4.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    status = get_binds_status(tmp_path)
    assert status["mismatch"] is True
    assert status["preset_lines"] == ["Custom", "Custom", "Custom", "ConsoleX360"]


def test_no_matching_binds_file_for_resolved_preset(tmp_path):
    (tmp_path / "StartPreset.4.start").write_text("ConsoleX360\nConsoleX360\nConsoleX360\nConsoleX360\n", encoding="utf-8")
    # No ConsoleX360.*.binds file on disk -- only an unrelated preset exists.
    (tmp_path / "Custom.4.2.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    status = get_binds_status(tmp_path)
    assert status["resolved_preset"] == "ConsoleX360"
    assert status["binds_file"] is None
    assert status["mismatch"] is False


def test_picks_highest_version_binds_file(tmp_path):
    (tmp_path / "StartPreset.4.start").write_text("Custom\nCustom\nCustom\nCustom\n", encoding="utf-8")
    (tmp_path / "Custom.4.1.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    (tmp_path / "Custom.4.4.binds").write_text(_MINIMAL_BINDS_XML, encoding="utf-8")
    status = get_binds_status(tmp_path)
    assert status["binds_file"] == "Custom.4.4.binds"
