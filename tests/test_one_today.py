"""Every "today" in the app is UTC (edc.utils.dates.utc_today): a local date next
to UTC data dates a row a day ahead for UTC+ players near local midnight."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_local_today_in_app_code():
    hits = [f"{p.relative_to(ROOT)}:{n}"
            for folder in ("edc", "persistence") for p in (ROOT / folder).rglob("*.py")
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "date.today(" in line.split("#")[0]]
    assert hits == []
