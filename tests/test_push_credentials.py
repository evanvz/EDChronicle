# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

from edc.core.push_credentials import (
    EDSM, RAVEN, clear_key, load_key, protect, save_key, unprotect,
)
from persistence.database import Database
from persistence.schema import SCHEMA_SQL


def _db(tmp_path):
    db = Database(tmp_path / "t.db")
    db.executescript(SCHEMA_SQL)
    return db


def test_protect_round_trip():
    assert unprotect(protect(b"abc123")) == b"abc123"


def test_protected_bytes_hide_plaintext():
    assert b"abc123" not in protect(b"abc123")


def test_unprotect_garbage_returns_none():
    assert unprotect(b"not a dpapi blob") is None


def test_save_load_clear(tmp_path):
    db = _db(tmp_path)
    save_key(db, RAVEN, "B0B R0GERS", "k-1")
    assert load_key(db, RAVEN) == ("B0B R0GERS", "k-1")
    raw = db.execute("SELECT secret FROM push_credentials").fetchone()[0]
    assert b"k-1" not in bytes(raw)
    clear_key(db, RAVEN)
    assert load_key(db, RAVEN) is None


def test_load_undecryptable_is_none(tmp_path):
    db = _db(tmp_path)
    db.execute("INSERT INTO push_credentials VALUES ('edsm', 'X', x'00ff')")
    assert load_key(db, EDSM) is None
