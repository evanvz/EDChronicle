"""
One-off CLI tool to backfill the `systems` table from the commander's
personal EDSM flight log — for systems visited before local journal
history exists (e.g. Xbox-era play, which never produced PC journal
files at all). Never overwrites a system the journal already knows about
(see repo.save_system_from_flight_log()).

EDSM's api-logs-v1/get-logs silently caps how much history one request
can return -- passing a wide startDateTime/endDateTime span (or none at
all, which defaults to the last 7 days) came back with zero entries for
a real commander with 12,000+ systems visited, no error either time.
Confirmed against EDDiscovery's own EDSM sync source (EDSMLogFetcher.cs,
proven to work) that the real pattern is one request per 7-day window,
walked forward from an anchor date to now -- so that's what this does.
For ~7-11 years of history that's roughly 400-600 requests; at the
throttle below (safely under EDSM's 360 requests/hour for this endpoint)
that's on the order of an hour, not a quick one-off -- expected, not a
bug, and progress prints per chunk so it's clear it's still working.

Usage:
  python tools/import_edsm_flight_log.py --commander "CMDR Name" --api-key "..."
  python tools/import_edsm_flight_log.py --commander "CMDR Name" --api-key "..." --since 2018-12-01 --until 2021-01-01
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "edhelper.db"
# Running this file directly (`python tools/import_edsm_flight_log.py`) sets
# sys.path[0] to tools/, not the repo root -- persistence/ lives one level
# up, so it's unimportable without this (confirmed live 2026-08-29).
sys.path.insert(0, str(Path(__file__).parent.parent))
_LOGS_URL = "https://www.edsm.net/api-logs-v1/get-logs"
_TIMEOUT = 60
# See edc/core/edsm_faction_lookup.py -- EDSM's Cloudflare front-end 403s
# the default python-requests User-Agent specifically.
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"
_EDSM_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
# EDSM's own launch date -- no flight log entry can predate it. Matches
# EDDiscovery's EliteReleaseDates.EDSMRelease anchor.
_EDSM_LAUNCH_DATE = "2015-06-01"
_WINDOW_DAYS = 7
# EDSM publishes 360 requests/hour for this endpoint (~1 per 10s) --
# 10.5s keeps a safe margin rather than riding the limit exactly.
_MIN_REQUEST_INTERVAL_S = 10.5
_RETRY_DELAYS_S = (2.0, 5.0, 10.0)


def _fetch_window(commander: str, api_key: str, start: datetime, end: datetime) -> list[dict]:
    """One request for one date window. Returns [] on a genuine EDSM
    error after retries are exhausted (logged, not raised) -- a single
    bad week must not abort an hour-long run; the caller reports which
    windows were skipped so they can be re-run narrowly if needed."""
    params = {
        "commanderName": commander, "apiKey": api_key, "showId": 1,
        "startDateTime": start.strftime(_EDSM_DATETIME_FMT),
        "endDateTime": end.strftime(_EDSM_DATETIME_FMT),
    }
    for attempt in range(len(_RETRY_DELAYS_S) + 1):
        try:
            resp = requests.get(_LOGS_URL, params=params, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            data = None
        if data is not None and data.get("msgnum") == 100:
            return data.get("logs") or []
        if attempt < len(_RETRY_DELAYS_S):
            time.sleep(_RETRY_DELAYS_S[attempt])
    print(f"  WARNING: window {start.date()}..{end.date()} failed after retries, skipped.")
    return []


def fetch_flight_log(commander: str, api_key: str, since: str, until: str) -> list[dict]:
    """Walks [since, until) in _WINDOW_DAYS-day chunks, one request per
    chunk (see module docstring for why this can't be a single request),
    and returns every log entry found across all of them."""
    start = datetime.strptime(since, "%Y-%m-%d")
    end_bound = datetime.strptime(until, "%Y-%m-%d")
    window = timedelta(days=_WINDOW_DAYS)
    total_windows = max(1, -(-(end_bound - start) // window))  # ceil division

    all_logs: list[dict] = []
    i = 0
    while start < end_bound:
        i += 1
        chunk_end = min(start + window, end_bound)
        print(f"Window {i}/{total_windows}: {start.date()}..{chunk_end.date()}...")
        all_logs.extend(_fetch_window(commander, api_key, start, chunk_end))
        start = chunk_end
        if start < end_bound:
            time.sleep(_MIN_REQUEST_INTERVAL_S)
    return all_logs


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
    parser.add_argument("--since", default=_EDSM_LAUNCH_DATE, help="YYYY-MM-DD, default: EDSM's launch (full history)")
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
