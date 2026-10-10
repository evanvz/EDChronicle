"""Voice commands are on by default: fresh install, and a settings.json without the key."""
import json

from edc.config import ConfigStore


def test_voice_commands_default_on(tmp_path):
    store = ConfigStore(tmp_path)
    assert store.load().voice_commands_enabled is True

    store.ensure_dirs()
    store.path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    assert store.load().voice_commands_enabled is True
