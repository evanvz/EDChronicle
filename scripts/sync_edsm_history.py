import json
import os
import sqlite3
import sys
import time
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

EDSM_LOGS_URL = "https://www.edsm.net/api-logs-v1/get-logs"
EDSM_BODIES_URL = "https://www.edsm.net/api-system-v1/bodies"

DEFAULT_DB_PATH = Path("data") / "edhelper.db"
DEFAULT_CHECKPOINT = Path("data") / "edsm_sync_checkpoint.json"
REQUEST_DELAY_SECONDS = 11.0  # stay safely under EDSM 360 req/hour limit
HTTP_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5

def load_simple_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def edsm_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urlencode(params)
    req = Request(f"{url}?{query}", headers={"User-Agent": "EDHelper-EDSM-Sync/1.0"})
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = resp.read().decode("utf-8")
            return json.loads(data)
        except (TimeoutError, socket.timeout, URLError, HTTPError) as exc:
            last_exc = exc
            wait_s = min(60, 5 * attempt)
            print(f"[WARN] EDSM request failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                print(f"[WAIT] sleeping {wait_s}s before retry")
                time.sleep(wait_s)
            else:
                break
    raise RuntimeError(f"EDSM request failed after {MAX_RETRIES} attempts: {last_exc}")

def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_checkpoint(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: Path, payload: Dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def system_exists(conn: sqlite3.Connection, system_name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT system_address, system_name, body_count, fss_complete, first_visit, last_visit, visit_count
        FROM systems
        WHERE system_name = ?
        """,
        (system_name,),
    ).fetchone()


def system_has_bodies(conn: sqlite3.Connection, system_address: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM bodies WHERE system_address = ? LIMIT 1",
        (system_address,),
    ).fetchone()
    return row is not None


def upsert_system(
    conn: sqlite3.Connection,
    system_address: int,
    system_name: str,
    body_count: Optional[int],
    fss_complete: Optional[int],
    first_visit: Optional[str],
    last_visit: Optional[str],
    visit_count: Optional[int],
) -> None:
    conn.execute(
        """
        INSERT INTO systems (
            system_address,
            system_name,
            body_count,
            fss_complete,
            first_visit,
            last_visit,
            visit_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO UPDATE SET
            system_name = excluded.system_name,
            body_count = COALESCE(excluded.body_count, systems.body_count),
            fss_complete = COALESCE(excluded.fss_complete, systems.fss_complete),
            first_visit = CASE
                WHEN systems.first_visit IS NULL THEN excluded.first_visit
                WHEN excluded.first_visit IS NULL THEN systems.first_visit
                WHEN excluded.first_visit < systems.first_visit THEN excluded.first_visit
                ELSE systems.first_visit
            END,
            last_visit = CASE
                WHEN systems.last_visit IS NULL THEN excluded.last_visit
                WHEN excluded.last_visit IS NULL THEN systems.last_visit
                WHEN excluded.last_visit > systems.last_visit THEN excluded.last_visit
                ELSE systems.last_visit
            END,
            visit_count = CASE
                WHEN systems.visit_count IS NULL THEN excluded.visit_count
                WHEN excluded.visit_count IS NULL THEN systems.visit_count
                WHEN excluded.visit_count > systems.visit_count THEN excluded.visit_count
                ELSE systems.visit_count
            END
        """,
        (
            system_address,
            system_name,
            body_count,
            fss_complete,
            first_visit,
            last_visit,
            visit_count,
        ),
    )


def upsert_body(
    conn: sqlite3.Connection,
    system_address: int,
    body_id: int,
    body_name: str,
    planet_class: Optional[str],
    terraformable: Optional[int],
    landable: Optional[int],
    mapped: Optional[int],
    estimated_value: Optional[int],
    distance_ls: Optional[float],
) -> None:
    conn.execute(
        """
        INSERT INTO bodies (
            system_address,
            body_id,
            body_name,
            planet_class,
            terraformable,
            landable,
            mapped,
            estimated_value,
            distance_ls
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address, body_id) DO UPDATE SET
            body_name = excluded.body_name,
            planet_class = COALESCE(excluded.planet_class, bodies.planet_class),
            terraformable = COALESCE(excluded.terraformable, bodies.terraformable),
            landable = COALESCE(excluded.landable, bodies.landable),
            mapped = COALESCE(excluded.mapped, bodies.mapped),
            estimated_value = COALESCE(excluded.estimated_value, bodies.estimated_value),
            distance_ls = COALESCE(excluded.distance_ls, bodies.distance_ls)
        """,
        (
            system_address,
            body_id,
            body_name,
            planet_class,
            terraformable,
            landable,
            mapped,
            estimated_value,
            distance_ls,
        ),
    )


def fetch_logs_window(commander_name: str, api_key: str, start_dt: datetime, end_dt: datetime) -> Dict[str, Any]:
    return edsm_get(
        EDSM_LOGS_URL,
        {
            "commanderName": commander_name,
            "apiKey": api_key,
            "startDateTime": fmt_utc(start_dt),
            "endDateTime": fmt_utc(end_dt),
            "showId": 1,
        },
    )


def fetch_bodies_for_system(system_name: str) -> Dict[str, Any]:
    return edsm_get(
        EDSM_BODIES_URL,
        {
            "systemName": system_name,
        },
    )


def iter_week_windows(start_dt: datetime, end_dt: datetime) -> Iterable[tuple[datetime, datetime]]:
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + timedelta(days=7), end_dt)
        yield cur, nxt
        cur = nxt


def infer_estimated_value(body: Dict[str, Any]) -> Optional[int]:
    # EDSM may expose valuation-ish fields differently over time.
    # Keep this conservative and only store an int if clearly present.
    for key in ("estimatedValue", "estimated_value", "valueMax", "value"):
        val = body.get(key)
        if isinstance(val, int):
            return val
    return None


def sync_system_bodies(conn: sqlite3.Connection, system_name: str, system_address: int) -> int:
    payload = fetch_bodies_for_system(system_name)
    bodies = payload.get("bodies") or []
    count = 0

    for body in bodies:
        body_id = body.get("bodyId")
        body_name = body.get("name")
        if not isinstance(body_id, int) or not isinstance(body_name, str) or not body_name:
            continue

        sub_type = body.get("subType")
        terraformable = body.get("terraformingState")
        is_terraformable = None
        if isinstance(terraformable, str):
            is_terraformable = 0 if terraformable.lower() == "not terraformable" else 1

        is_landable = body.get("isLandable")
        landable = int(bool(is_landable)) if isinstance(is_landable, bool) else None

        was_mapped = body.get("wasMapped")
        mapped = int(bool(was_mapped)) if isinstance(was_mapped, bool) else None

        distance_ls = body.get("distanceToArrival")
        if not isinstance(distance_ls, (int, float)):
            distance_ls = None

        upsert_body(
            conn=conn,
            system_address=system_address,
            body_id=body_id,
            body_name=body_name,
            planet_class=sub_type if isinstance(sub_type, str) else None,
            terraformable=is_terraformable,
            landable=landable,
            mapped=mapped,
            estimated_value=infer_estimated_value(body),
            distance_ls=float(distance_ls) if distance_ls is not None else None,
        )
        count = 1

    return count


def main() -> int:
    load_simple_env(Path(".env"))

    commander_name = os.getenv("EDSM_COMMANDER_NAME", "").strip()
    api_key = os.getenv("EDSM_API_KEY", "").strip()
    db_path = Path(os.getenv("EDHELPER_DB_PATH", str(DEFAULT_DB_PATH)))
    checkpoint_path = Path(os.getenv("EDSM_SYNC_CHECKPOINT", str(DEFAULT_CHECKPOINT)))

    if not commander_name or not api_key:
        print("ERROR: Set EDSM_COMMANDER_NAME and EDSM_API_KEY in your environment or .env first.")
        return 1

    ensure_parent(db_path)
    conn = db_connect(db_path)

    checkpoint = load_checkpoint(checkpoint_path)
    start_s = checkpoint.get("next_start_utc")
    if start_s:
        start_dt = parse_utc(start_s)
    else:
        # Adjust if you want a later starting point for first run.
        start_dt = datetime(2018, 1, 1, tzinfo=timezone.utc)

    end_dt = utc_now()

    print(f"Syncing logs from {fmt_utc(start_dt)} to {fmt_utc(end_dt)}")

    imported_systems = 0
    imported_bodies = 0

    for win_start, win_end in iter_week_windows(start_dt, end_dt):
        print(f"[LOGS] {fmt_utc(win_start)} -> {fmt_utc(win_end)}")
        try:
            payload = fetch_logs_window(commander_name, api_key, win_start, win_end)
        except Exception as exc:
            print(f"ERROR: logs request failed for window {fmt_utc(win_start)} -> {fmt_utc(win_end)}: {exc}")
            save_checkpoint(checkpoint_path, {"next_start_utc": fmt_utc(win_start)})
            return 2

        if payload.get("msgnum") != 100:
            print(f"ERROR: EDSM logs request failed: {payload}")
            save_checkpoint(checkpoint_path, {"next_start_utc": fmt_utc(win_start)})
            return 2

        window_systems: Dict[str, Dict[str, Any]] = {}
        for entry in payload.get("logs") or []:
            system_name = entry.get("system")
            visit_date = entry.get("date")
            system_id = entry.get("systemId")
            if not isinstance(system_name, str) or not system_name:
                continue

            bucket = window_systems.setdefault(
                system_name,
                {
                    "system_name": system_name,
                    "first_visit": visit_date,
                    "last_visit": visit_date,
                    "visit_count": 0,
                    "edsm_system_id": system_id,
                },
            )
            if isinstance(visit_date, str):
                if not bucket["first_visit"] or visit_date < bucket["first_visit"]:
                    bucket["first_visit"] = visit_date
                if not bucket["last_visit"] or visit_date > bucket["last_visit"]:
                    bucket["last_visit"] = visit_date
            bucket["visit_count"] = 1

        print(f"[WINDOW] unique systems in window: {len(window_systems)}")

        for system_name, meta in sorted(window_systems.items()):
            row = system_exists(conn, system_name)

            if row is not None and isinstance(row["system_address"], int):
                system_address = row["system_address"]
            else:
                system_address = -abs(hash(system_name)) % (2**31)

            upsert_system(
                conn=conn,
                system_address=system_address,
                system_name=system_name,
                body_count=None,
                fss_complete=None,
                first_visit=meta["first_visit"],
                last_visit=meta["last_visit"],
                visit_count=meta["visit_count"],
            )
            imported_systems = 1

            if system_has_bodies(conn, system_address):
                continue

            try:
                body_count = sync_system_bodies(conn, system_name, system_address)
                imported_bodies = body_count
                print(f"[BODIES] {system_name}: {body_count}")
            except Exception as exc:
                print(f"[WARN] bodies fetch failed for {system_name}: {exc}")

            time.sleep(REQUEST_DELAY_SECONDS)

        conn.commit()
        save_checkpoint(checkpoint_path, {"next_start_utc": fmt_utc(win_end)})
        print(f"[PROGRESS] systems upserted: {imported_systems}, bodies imported: {imported_bodies}")
        time.sleep(REQUEST_DELAY_SECONDS)

    conn.commit()
    print(f"Done. Systems upserted: {imported_systems}, bodies imported: {imported_bodies}")
    return 0


if __name__ == "__main__":
   raise SystemExit(main())