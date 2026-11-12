"""write_text_atomic() -- a failed write must leave the old file whole
(settings.json holds API keys; an in-place write could truncate it)."""
import pytest

from edc.utils import files
from edc.utils.files import write_text_atomic


def test_writes_and_replaces(tmp_path):
    p = tmp_path / "settings.json"
    write_text_atomic(p, "one")
    write_text_atomic(p, "two")
    assert p.read_text(encoding="utf-8") == "two"
    assert not (tmp_path / "settings.json.tmp").exists()


def test_failed_swap_keeps_the_old_file(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("old", encoding="utf-8")

    def boom(*_a):
        raise OSError("disk gone")
    monkeypatch.setattr(files.os, "replace", boom)
    with pytest.raises(OSError):
        write_text_atomic(p, "new")
    assert p.read_text(encoding="utf-8") == "old"
