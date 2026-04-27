"""
CLI tool to inspect and clear spansh_bodies cache entries.

Usage:
  python tools/clear_spansh_cache.py              -- list all cached systems
  python tools/clear_spansh_cache.py --all        -- delete all spansh_bodies rows
  python tools/clear_spansh_cache.py <address>    -- delete rows for one system address
  python tools/clear_spansh_cache.py <address> --list  -- show bodies for one system
"""
import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "edhelper.db"


def get_conn():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list_systems(conn):
    rows = conn.execute(
        """
        SELECT sb.system_address, s.system_name,
               COUNT(sb.body_name) AS cached_bodies
        FROM spansh_bodies sb
        LEFT JOIN systems s ON s.system_address = sb.system_address
        GROUP BY sb.system_address
        ORDER BY s.system_name
        """
    ).fetchall()
    if not rows:
        print("spansh_bodies table is empty.")
        return
    print(f"{'Address':>18}  {'System':<30}  Bodies")
    print("-" * 60)
    for r in rows:
        print(f"{r['system_address']:>18}  {r['system_name'] or '(unknown)':<30}  {r['cached_bodies']}")


def cmd_list_bodies(conn, address: int):
    rows = conn.execute(
        "SELECT body_name, planet_class, distance_ls, estimated_value, landable "
        "FROM spansh_bodies WHERE system_address = ? ORDER BY distance_ls",
        (address,),
    ).fetchall()
    if not rows:
        print(f"No spansh_bodies for address {address}.")
        return
    print(f"{'Body':<35}  {'Class':<25}  {'Dist':>8}  {'Est Value':>10}  Landable")
    print("-" * 95)
    for r in rows:
        land = {1: "yes", 0: "no"}.get(r["landable"], "?")
        print(f"{r['body_name']:<35}  {r['planet_class'] or '':<25}  {r['distance_ls'] or 0:>8.1f}  {r['estimated_value'] or 0:>10,}  {land}")


def cmd_delete(conn, address: int):
    cur = conn.execute("DELETE FROM spansh_bodies WHERE system_address = ?", (address,))
    conn.commit()
    print(f"Deleted {cur.rowcount} row(s) for address {address}.")


def cmd_delete_all(conn):
    cur = conn.execute("DELETE FROM spansh_bodies")
    conn.commit()
    print(f"Deleted {cur.rowcount} row(s) from spansh_bodies.")


def main():
    parser = argparse.ArgumentParser(description="Manage EDChronicle Spansh body cache.")
    parser.add_argument("address", nargs="?", type=int, help="System address to target")
    parser.add_argument("--all",  action="store_true", help="Delete all cached entries")
    parser.add_argument("--list", action="store_true", help="List bodies for the given address")
    args = parser.parse_args()

    conn = get_conn()

    if args.all:
        cmd_delete_all(conn)
    elif args.address and args.list:
        cmd_list_bodies(conn, args.address)
    elif args.address:
        cmd_delete(conn, args.address)
    else:
        cmd_list_systems(conn)

    conn.close()


if __name__ == "__main__":
    main()
