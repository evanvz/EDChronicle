import sqlite3

from persistence.schema import SCHEMA_SQL
from tools.app_status.importer_compare import diff_tables


def _db():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA_SQL)
    return c


def _body(c, bid):
    c.execute("INSERT INTO bodies (system_address, body_id, body_name) VALUES (1, ?, 'x')", (bid,))


def test_differing_body_row_is_reported_and_identical_is_clean():
    a, b = _db(), _db()
    _body(a, 1)
    _body(b, 1)
    assert diff_tables(a, b, ["bodies"]) == []
    _body(a, 2)
    out = diff_tables(a, b, ["bodies"])
    assert len(out) == 1 and out[0].startswith("import vs live: bodies live=2 import=1, 1 rows differ")
