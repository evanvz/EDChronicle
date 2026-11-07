import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.app_status.areas import area_of
from tools.app_status.replay import journal_files

_TAIL_BYTES = 65536
# 2026-11-07 10:22:03,775 [ERROR] [edc.core.x] message  (app log times are local, UTC+2)
_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \[(\w+)\] \[([^\]]+)\] (.*)$")
_LOG_NAME = re.compile(r"^edc_(\d{4})-(\d\d)-(\d\d)_\d+\.log$")


def copy_db(src: Path, dst: Path) -> None:
    ro = sqlite3.connect(Path(src).resolve().as_uri() + "?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        ro.backup(out)
    finally:
        out.close()
        ro.close()


def _parse(s) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def newest_event_time(journal_dir: Path) -> datetime | None:
    files = journal_files(journal_dir, None)
    if not files:
        return None
    with open(files[-1], "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - _TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = _parse(evt.get("timestamp")) if isinstance(evt, dict) else None
        if t:
            return t
    return None


def _info(area: str, text: str) -> dict:
    return {"area": area, "check": "freshness", "severity": "info", "text": text}


def check_freshness(db_copy: Path, areas: dict, newest_event: datetime | None, now: datetime) -> dict:
    t0 = time.time()
    cells, findings = {}, []
    if newest_event is None:
        newest_event = now
        findings.append(_info("Other", "no journals found: play clock measured against now"))
    conn = sqlite3.connect(db_copy)
    try:
        for area, a in areas.items():
            dates, stale = [], []
            for e in a.get("fresh", []):
                tbl, col, clock = e["table"], e["column"], e["clock"]
                try:
                    raw = conn.execute(f'SELECT MAX("{col}") FROM "{tbl}"').fetchone()[0]
                except sqlite3.Error as ex:
                    findings.append(_info(area, f"{tbl}.{col} not checked: {ex}"))
                    continue
                d = _parse(raw)
                if d is None:
                    findings.append(_info(area, f"{tbl}.{col} MAX not parseable: {raw!r}"))
                    continue
                age = ((newest_event if clock == "play" else now) - d).days
                day = d.date().isoformat()
                if age > e["max_days"]:
                    stale.append(day)
                    findings.append({"area": area, "check": "freshness", "severity": "stale",
                                     "text": f"{tbl}.{col} last {day}, {age} days before {clock}"})
                else:
                    dates.append(day)
            if stale:
                cells[area] = f"STALE {min(stale)}"
            elif dates:
                cells[area] = max(dates)
    finally:
        conn.close()
    return {"cells": cells, "findings": findings, "seconds": time.time() - t0}


def run_freshness(db_path: Path, journal_dir, areas: dict, now: datetime) -> dict:
    if not Path(db_path).exists():
        return {"cells": {}, "seconds": 0.0, "findings": [
            {"area": "Other", "check": "freshness", "severity": "stale", "text": "no database found"}]}
    newest = newest_event_time(Path(journal_dir)) if journal_dir else None
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        dst = Path(tmp) / "copy.db"
        copy_db(db_path, dst)
        return check_freshness(dst, areas, newest, now)


def scan_logs(logs_dir: Path, days: int, areas: dict, now: datetime) -> dict:
    t0 = time.time()
    cutoff = (now - timedelta(days=days)).date()
    errors, tracebacks, msgs = {}, {}, {}
    for p in sorted(Path(logs_dir).glob("edc_*.log")):
        m = _LOG_NAME.match(p.name)
        if not m or datetime(*map(int, m.groups())).date() < cutoff:
            continue
        last = None
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG_LINE.match(line)
                if m:
                    last = m.group(2)
                    if m.group(1) == "ERROR":
                        errors[last] = errors.get(last, 0) + 1
                        c = msgs.setdefault(last, {})
                        c[m.group(3)[:120]] = c.get(m.group(3)[:120], 0) + 1
                elif last and line.startswith("Traceback"):
                    tracebacks[last] = tracebacks.get(last, 0) + 1
    per_area, findings = {}, []
    for lg in sorted(set(errors) | set(tracebacks)):
        n, tb = errors.get(lg, 0), tracebacks.get(lg, 0)
        area = area_of(lg.replace(".", "/") + ".py", "module", areas) if lg.startswith("edc.") else "Other"
        per_area[area] = per_area.get(area, 0) + n
        top = max(msgs[lg], key=msgs[lg].get) if lg in msgs else ""
        findings.append({"area": area, "check": "logs", "severity": "replay",
                         "text": f"{lg}: {n} errors, {tb} tracebacks in {days} days; top: {top}"})
    cells = {a: f"{n} errors" if n else "0" for a, n in per_area.items()}
    return {"cells": cells, "findings": findings, "seconds": time.time() - t0}
