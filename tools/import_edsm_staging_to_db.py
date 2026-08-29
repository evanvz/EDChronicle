"""
One-off CLI tool to merge the EDSM flight log staging DB (built by
tools/import_edsm_flight_log.py) into the real personal DB (edhelper.db).

Insert-only via repo.save_system_from_flight_log() -- never overwrites a
system the journal already knows about. Safe to re-run: rows already
present in edhelper.db are silently left untouched.

Usage:
  python tools/import_edsm_staging_to_db.py
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "edhelper.db"
STAGING_DB_PATH = Path(__file__).parent.parent / "data" / "edsm_staging.db"
# Running this file directly (`python tools/import_edsm_staging_to_db.py`)
# sets sys.path[0] to tools/, not the repo root -- persistence/ lives one
# level up, so it's unimportable without this (confirmed live 2026-08-29).
sys.path.insert(0, str(Path(__file__).parent.parent))


def read_staged_systems(staging_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(staging_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT system_address, system_name, first_visit, last_visit, visit_count, first_discovery FROM staged_systems"
    ).fetchall()
    conn.close()
    return rows


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")
    if not STAGING_DB_PATH.exists():
        raise SystemExit(f"Staging DB not found: {STAGING_DB_PATH} -- run tools/import_edsm_flight_log.py first.")

    rows = read_staged_systems(STAGING_DB_PATH)
    print(f"{len(rows)} systems in staging.")
    if not rows:
        return

    from persistence.database import Database
    from persistence.repository import Repository

    db = Database(DB_PATH)
    db.run_migrations()
    repo = Repository(db)
    before = {row["system_address"]: repo.get_system(row["system_address"]) for row in rows}
    for row in rows:
        repo.save_system_from_flight_log(
            system_address=row["system_address"],
            system_name=row["system_name"],
            first_visit=row["first_visit"],
            last_visit=row["last_visit"],
            visit_count=row["visit_count"],
            first_discovery=row["first_discovery"],
        )
    inserted = sum(1 for row in rows if before[row["system_address"]] is None)
    skipped_existing = len(rows) - inserted
    db.close()

    print(f"Inserted {inserted} new system(s).")
    print(f"Left {skipped_existing} already-known system(s) untouched.")


if __name__ == "__main__":
    main()
