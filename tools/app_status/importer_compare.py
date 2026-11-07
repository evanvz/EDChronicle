import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from tools.app_status.areas import AREAS_PATH, AREA_ORDER, load_json
from tools.app_status.replay import _table_area, journal_files, table_counts

_TS = re.compile(r"timestamp|_at$|^time", re.I)


def _key_cols(conn, table):
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    if pk and not (len(pk) == 1 and info[[r[1] for r in info].index(pk[0])][2].upper() == "INTEGER"):
        return pk  # a lone INTEGER pk is a surrogate rowid: differs by construction
    return [r[1] for r in info if r[1] not in pk and not _TS.search(r[1])]


def _keys(conn, table, cols):
    sel = ", ".join(f'"{c}"' for c in cols)
    return {tuple(r) for r in conn.execute(f'SELECT {sel} FROM "{table}"')}


def _diff(live, imported, tables):
    out = []
    for t in tables:
        n = live.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        m = imported.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        cols = _key_cols(live, t)
        a, b = _keys(live, t, cols), _keys(imported, t, cols)
        if n != m or a != b:
            diff = sorted(a ^ b, key=repr)
            ex = "; ".join(("live " if d in a else "import ") + repr(d)[:100] for d in diff[:3])
            out.append((t, f"import vs live: {t} live={n} import={m}, {len(diff)} rows differ (e.g. {ex})"))
    return out


def diff_tables(live: sqlite3.Connection, imported: sqlite3.Connection, tables: list[str]) -> list[str]:
    return [text for _, text in _diff(live, imported, tables)]


def compare_paths(repo_root: Path, journal_dir: str, days: int | None, live_db: Path) -> dict:
    from edc.core.journal_importer import JournalImporter
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL

    t0 = time.time()
    areas = load_json(AREAS_PATH)
    findings = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        jdir = Path(tmp) / "journals"
        jdir.mkdir()
        for f in journal_files(Path(journal_dir), days):
            shutil.copy2(f, jdir / f.name)
        (Path(tmp) / "imp").mkdir()  # own dir: Database attaches a sibling network_cache.db
        db = Database(Path(tmp) / "imp" / "imp.db")
        live = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
        try:
            db.executescript(SCHEMA_SQL)
            db.run_migrations()
            JournalImporter(jdir, Repository(db)).import_all()
            db.conn.commit()
            la, im = table_counts(live), table_counts(db.conn)
            tables = [t for t in la if not t.startswith("net.") and t != "processed_journals" and (la[t] or im.get(t))]
            for t, text in _diff(live, db.conn, tables):
                findings.append({"area": _table_area(t, areas), "check": "importer", "severity": "suspect",
                                 "text": text})
            counts = ", ".join(f"{t} {la[t]}/{im.get(t, 0)}" for t in tables)
        finally:
            live.close()
            db.close()
    findings.append({"area": "Other", "check": "importer", "severity": "info",
                     "text": "importer compared on main-DB tables only (net.* not in the live copy); "
                             f"live/import counts: {counts}"})
    bad = {f["area"] for f in findings if f["severity"] == "suspect"}
    cells = {a: "differs" if a in bad else "ok" for a in AREA_ORDER}
    return {"cells": cells, "findings": findings, "seconds": time.time() - t0}
