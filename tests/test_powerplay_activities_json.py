"""The shipped activity table must parse: a bad quote in a note once made the
loader skip the whole file with only a log warning (fc28ccc)."""
import json
from pathlib import Path


def test_shipped_powerplay_activities_json_parses():
    path = Path(__file__).resolve().parent.parent / "settings" / "powerplay_activities.json"
    assert json.loads(path.read_text(encoding="utf-8"))
