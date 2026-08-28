"""
One-off CLI tool to backfill the `systems` table from the commander's
personal EDSM flight log — for systems visited before local journal
history exists (e.g. Xbox-era play, which never produced PC journal
files at all). Never overwrites a system the journal already knows about
(see repo.save_system_from_flight_log()).

EDSM's api-logs-v1/get-logs returns the whole flight log for a date range
in one response, not paginated -- this tool makes exactly one request,
nowhere near EDSM's 360 requests/hour limit for this endpoint. IMPORTANT:
confirmed live -- if startDateTime/endDateTime aren't given, EDSM quietly
defaults to the last 7 days only, not your full history (a genuine
commander with 12,000+ systems visited got an empty response with no
error, just a 7-day startDateTime/endDateTime in the reply). Defaults
here to 2014-01-01 (Elite Dangerous's actual launch) through now, so a
bare run covers full history unless narrowed with --since/--until.

Usage:
  python tools/import_edsm_flight_log.py --commander "CMDR Name" --api-key "..."
  python tools/import_edsm_flight_log.py --commander "CMDR Name" --api-key "..." --since 2018-01-01 --until 2021-01-01
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "edhelper.db"
_LOGS_URL = "https://www.edsm.net/api-logs-v1/get-logs"
_TIMEOUT = 60
# See edc/core/edsm_faction_lookup.py -- EDSM's Cloudflare front-end 403s
# the default python-requests User-Agent specifically.
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"
_EDSM_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_ELITE_LAUNCH_DATE = "2014-01-01"


def fetch_flight_log(commander: str, api_key: str, since: str, until: str) -> list[dict]:
    start = datetime.strptime(since, "%Y-%m-%d").strftime(_EDSM_DATETIME_FMT)
    end = datetime.strptime(until, "%Y-%m-%d").strftime(_EDSM_DATETIME_FMT)
    resp = requests.get(
        _LOGS_URL,
        params={
            "commanderName": commander, "apiKey": api_key, "showId": 1,
            "startDateTime": start, "endDateTime": end,
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("msgnum") != 100:
        raise SystemExit(f"EDSM error: {data.get('msg', data)}")
    return data.get("logs") or []


def group_by_system(logs: list[dict]) -> dict[int, dict]:
    """One row per system_address: earliest/latest visit date, visit count,
    and whether any visit had EDSM's firstDiscover flag set. Entries
    missing systemId64 (e.g. a duplicate-name system EDSM couldn't
    resolve) are skipped -- systems can only be keyed by the game's real
    address, not EDSM's own internal id."""
    systems: dict[int, dict] = {}
    skipped = 0
    for entry in logs:
        address = entry.get("systemId64")
        name = entry.get("system")
        date = entry.get("date")
        if not isinstance(address, int) or not name or not date:
            skipped += 1
            continue
        row = systems.setdefault(address, {
            "system_name": name,
            "first_visit": date,
            "last_visit": date,
            "visit_count": 0,
            "first_discovery": 0,
        })
        row["visit_count"] += 1
        if date < row["first_visit"]:
            row["first_visit"] = date
        if date > row["last_visit"]:
            row["last_visit"] = date
        if entry.get("firstDiscover"):
            row["first_discovery"] = 1
    if skipped:
        print(f"Skipped {skipped} log entr{'y' if skipped == 1 else 'ies'} with no resolvable system address.")
    return systems


def main():
    parser = argparse.ArgumentParser(description="Backfill systems from your personal EDSM flight log.")
    parser.add_argument("--commander", required=True, help="Commander name as registered on EDSM")
    parser.add_argument("--api-key", required=True, help="Your EDSM API key (Settings > My API Key)")
    parser.add_argument("--since", default=_ELITE_LAUNCH_DATE, help="YYYY-MM-DD, default: Elite Dangerous's launch (full history)")
    parser.add_argument("--until", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="YYYY-MM-DD, default: today")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    logs = fetch_flight_log(args.commander, args.api_key, args.since, args.until)
    print(f"EDSM flight log ({args.since} to {args.until}): {len(logs)} entries.")
    if not logs:
        print("Nothing to import for this range.")
        return
    systems = group_by_system(logs)
    print(f"{len(systems)} distinct systems.")

    from persistence.database import Database
    from persistence.repository import Repository

    db = Database(DB_PATH)
    repo = Repository(db)
    before = {addr: repo.get_system(addr) for addr in systems}
    for address, row in systems.items():
        repo.save_system_from_flight_log(
            system_address=address,
            system_name=row["system_name"],
            first_visit=row["first_visit"],
            last_visit=row["last_visit"],
            visit_count=row["visit_count"],
            first_discovery=row["first_discovery"],
        )
    inserted = sum(1 for addr in systems if before[addr] is None)
    skipped_existing = len(systems) - inserted
    db.close()

    print(f"Inserted {inserted} new system(s).")
    print(f"Left {skipped_existing} already-known system(s) untouched.")


if __name__ == "__main__":
    main()
