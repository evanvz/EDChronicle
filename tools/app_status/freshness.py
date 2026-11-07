import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.app_status.areas import area_of_logger
from tools.app_status.replay import journal_files

REPO_ROOT = Path(__file__).resolve().parents[2]
_TAIL_BYTES = 65536
# 2026-11-07 10:22:03,775 [ERROR] [edc.core.x] message  (app log times are local, UTC+2)
_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \[(\w+)\] \[([^\]]+)\] (.*)$")
_NETWORK = re.compile(
    r"[45]\d\d (?:Client|Server) Error|requests\.exceptions\.(?:ConnectionError|ReadTimeout|ConnectTimeout|Timeout)"
    r"|timed? ?out|Connection (?:refused|reset|aborted)|Connection(?:Refused|Reset|Aborted)Error|Max retries exceeded"
    r"|SSLError|getaddrinfo failed|Name or service not known|NameResolutionError", re.I)
_EXC_LINE = re.compile(r"^\w[\w.]*(?:Error|Exception|Timeout)\b.*", re.M)
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
            dates, stale, empty = [], [], False
            for e in a.get("fresh", []):
                tbl, col, clock = e["table"], e["column"], e["clock"]
                try:
                    raw = conn.execute(f'SELECT MAX("{col}") FROM "{tbl}"').fetchone()[0]
                except sqlite3.Error as ex:
                    findings.append(_info(area, f"{tbl}.{col} not checked: {ex}"))
                    continue
                if raw is None:
                    empty = True
                    findings.append(_info(area, f"{tbl}.{col} no data"))
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
            if empty:
                cells[area] = f"{cells[area]}; no data" if area in cells else "no data"
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


def _top(counter: dict) -> str:
    return max(counter, key=counter.get) if counter else ""


def scan_logs(logs_dir: Path, days: int, areas: dict, now: datetime) -> dict:
    t0 = time.time()
    cutoff = (now - timedelta(days=days)).date()
    files = [p for p in sorted(Path(logs_dir).glob("edc_*.log"))
             if (m := _LOG_NAME.match(p.name)) and datetime(*map(int, m.groups())).date() >= cutoff]
    records = []  # [logger, message, continuation text] per ERROR line
    for p in files:
        cur = None
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG_LINE.match(line)
                if m:
                    cur = [m.group(2), m.group(3), ""] if m.group(1) == "ERROR" else None
                    if cur:
                        records.append(cur)
                elif cur:
                    cur[2] += line
    errors, tracebacks, msgs, net, net_msgs = {}, {}, {}, {}, {}
    for lg, msg, extra in records:
        if _NETWORK.search(" ".join([msg] + _EXC_LINE.findall(extra))):
            net[lg] = net.get(lg, 0) + 1
            c = net_msgs.setdefault(lg, {})
            c[msg[:120]] = c.get(msg[:120], 0) + 1
            continue
        errors[lg] = errors.get(lg, 0) + 1
        tracebacks[lg] = tracebacks.get(lg, 0) + extra.count("Traceback (most recent")
        c = msgs.setdefault(lg, {})
        c[msg[:120]] = c.get(msg[:120], 0) + 1

    per_area = {a: 0 for a in areas}
    findings = []
    if not files:
        findings.append({"area": "Other", "check": "logs", "severity": "info",
                         "text": f"no log files in last {days} days ({logs_dir})"})
    for lg in sorted(errors):
        a = area_of_logger(lg, REPO_ROOT, areas)
        per_area[a] = per_area.get(a, 0) + errors[lg]
        findings.append({"area": a, "check": "logs", "severity": "replay",
                         "text": f"{lg}: {errors[lg]} errors, {tracebacks[lg]} tracebacks in {days} days; top: {_top(msgs[lg])}"})
    for lg in sorted(net):
        findings.append({"area": area_of_logger(lg, REPO_ROOT, areas), "check": "logs", "severity": "info",
                         "text": f"{lg}: {net[lg]} network errors (EDSM/Spansh unreachable or rate-limited): {_top(net_msgs[lg])}"})
    cells = {a: f"{n} errors" if n else "0" for a, n in per_area.items()}
    return {"cells": cells, "findings": findings, "seconds": time.time() - t0}
