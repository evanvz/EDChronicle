import json
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterator

from tools.app_status.areas import AREAS_PATH, AREA_ORDER, BASELINES_PATH, area_of_logger, load_json
from tools.app_status.sandbox import (
    _area_from_exc, block_network, blocked_note, build_window, capture_errors, make_app_dir, release_errors, unblock_network)

_NEW = re.compile(r"Journal\.(\d{4})-(\d{2})-(\d{2})T")
_OLD = re.compile(r"Journal\.(\d{2})(\d{2})(\d{2})\d{6}\.")
EXOBIO, MISSIONS, BGS, COLONY, TRADE = ("Exploration & exobiology", "Missions", "BGS & factions",
                                        "Colonisation & system planner", "Trade, markets & routes")


def _file_date(p: Path):
    m = _NEW.match(p.name)
    if m:
        return date(*map(int, m.groups()))
    m = _OLD.match(p.name)
    if m:
        y, mo, d = map(int, m.groups())
        return date(2000 + y, mo, d)
    return None


def journal_files(journal_dir: Path, days: int | None) -> list[Path]:
    files = sorted((p for p in Path(journal_dir).glob("Journal.*.log") if _file_date(p)),
                   key=lambda p: (_file_date(p), p.name))
    if days is None or not files:
        return files
    newest = _file_date(files[-1])
    return [p for p in files if (newest - _file_date(p)).days <= days]


def read_events(path: Path, bad: list) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                bad.append((path.name, no))
                continue
            if isinstance(evt, dict):
                yield evt


def table_counts(conn) -> dict[str, int]:
    out = {}
    for schema in [r[1] for r in conn.execute("PRAGMA database_list") if r[1] in ("main", "net")]:
        prefix = "" if schema == "main" else "net."
        for (name,) in conn.execute(
                f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            out[prefix + name] = conn.execute(f'SELECT COUNT(*) FROM {schema}."{name}"').fetchone()[0]
    return out


def _record_area(rec, repo_root: Path, areas: dict) -> str:
    if rec.exc_info and rec.exc_info[1] is not None:
        a = _area_from_exc(rec.exc_info[1], repo_root, areas)
        if a != "Other":
            return a
    return area_of_logger(rec.name, repo_root, areas)


def _is_bio(evt) -> bool:
    return any("biological" in str(s.get("Type") or "").lower() for s in evt.get("Signals") or []
               if isinstance(s, dict))


def _species_predicted(pred, genus: str, species: str) -> bool:
    from edc.core.exo_predictor import genus_key
    sp = species.strip().lower()
    names = {s.lower() for lst in pred.possible.values() for s, _ in lst}
    names |= {s.lower() for s, _ in pred.known.values()}
    return sp in names or genus_key(genus) in {genus_key(g) for g in pred.sampled}


def _table_area(table: str, areas: dict) -> str:
    name = table.removeprefix("net.")
    return next((a for a, v in areas.items() if any(f.get("table") == name for f in v.get("fresh", []))), "Other")


def _feed(app, win, files, bad, after, on_exc):
    n = 0
    for path in files:
        for evt in read_events(path, bad):
            try:
                win._on_event(evt)
            except Exception as e:
                on_exc(evt, e)
            try:
                after(evt)
            except Exception as e:
                on_exc(evt, e, "sanity check: ")
            n += 1
            if n % 500 == 0:
                app.processEvents()
    app.processEvents()
    return n


def run_replay(repo_root: Path, journal_dir: str | None, days: int | None, keep_db: Path | None = None) -> dict:
    t0 = time.time()
    if not journal_dir or not Path(journal_dir).is_dir():
        return {"cells": {}, "seconds": time.time() - t0, "stats": {},
                "findings": [{"area": "Other", "check": "replay", "severity": "replay",
                              "text": "replay not run: no journal dir"}]}
    repo_root = Path(repo_root)
    areas = load_json(AREAS_PATH)
    baselines = load_json(BASELINES_PATH)
    files = journal_files(Path(journal_dir), days)
    if not files:
        return {"cells": {}, "seconds": time.time() - t0, "stats": {},
                "findings": [{"area": "Other", "check": "replay", "severity": "replay",
                              "text": f"replay not run: no journal files in {journal_dir}"}]}
    findings, errs, bad = [], Counter(), []
    seen = Counter()
    misses = Counter()
    bio_preds = {}  # (SystemAddress, BodyID) -> latest prediction from a bio-signal check
    pending = {}  # body name -> (SystemAddress, BodyID): FSSBodySignals fires before the body's own Scan

    def on_exc(evt, e, tag=""):
        errs[(_area_from_exc(e, repo_root, areas),
              f"{tag}{evt.get('event')}: {type(e).__name__}: {e}")] += 1

    def check_bio(body, key):
        preds = win._exo_predictions()
        seen["_bio"] += 1
        if body in preds:
            bio_preds[key] = preds[body]
        else:
            misses["exobio_bio_bodies_unpredicted"] += 1

    def sanity(evt):
        name = evt.get("event")
        body = evt.get("BodyName")
        seen[name] += 1
        if name in ("FSSBodySignals", "SAASignalsFound") and _is_bio(evt):
            key = (evt.get("SystemAddress"), evt.get("BodyID"))
            if (win.state.bodies.get(body) or {}).get("PlanetClass"):
                check_bio(body, key)
            else:
                pending[body] = key
        elif name == "Scan" and body in pending:
            check_bio(body, pending.pop(body))
        elif name in ("FSDJump", "Location") and evt.get("Factions"):
            seen["_factions"] += 1
        elif name == "ScanOrganic" and evt.get("ScanType") == "Analyse":
            pred = bio_preds.get((evt.get("SystemAddress"), evt.get("Body")))
            if pred is not None:
                seen["_analyse"] += 1
                if not _species_predicted(pred, evt.get("Genus_Localised") or evt.get("Genus") or "",
                                          evt.get("Species_Localised") or evt.get("Species") or ""):
                    misses["exobio_sampled_misses"] += 1

    old_hook = sys.excepthook
    counter = block_network()
    records = capture_errors()
    stats = {"files": len(files), "events": 0, "pass1_seconds": 0.0, "pass2_seconds": 0.0, "bad_lines": 0}
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app_dir = make_app_dir(repo_root, Path(tmp))
            app, win, _ = build_window(app_dir, journal_dir)
            try:
                t1 = time.time()
                th = getattr(win, "_startup_history_thread", None)  # its result lands as DB writes; settle first
                if th is None:
                    findings.append({"area": "Other", "check": "replay", "severity": "info",
                                     "text": "no startup history scan thread to wait for"})
                elif not th.wait(120_000):
                    findings.append({"area": "Other", "check": "replay", "severity": "replay",
                                     "text": "startup history scan did not finish in 120 s"})
                app.processEvents()
                stats["events"] = _feed(app, win, files, bad, sanity, on_exc)
                stats["pass1_seconds"] = round(time.time() - t1, 1)
                stats["bad_lines"] = len(bad)
                n_rec1 = len(records)
                after1 = table_counts(win.db.conn)
                if keep_db is not None:
                    dst = sqlite3.connect(keep_db)
                    try:
                        win.db.conn.backup(dst)  # main DB only; net.* is not copied
                    finally:
                        dst.close()

                t2 = time.time()
                win._on_event({"event": "_BootstrapStart"})  # an app restart replays like journal_watcher does
                _feed(app, win, files, [], lambda e: None, lambda e, x, tag="": on_exc(e, x, "dedupe pass: " + tag))
                win._on_event({"event": "_BootstrapEnd"})
                stats["pass2_seconds"] = round(time.time() - t2, 1)
                after2 = table_counts(win.db.conn)
                misses["mission_completion_duplicates"] = win.db.conn.execute(
                    "SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) n FROM faction_mission_completions "
                    "WHERE mission_id IS NOT NULL GROUP BY mission_id, system_address, faction_name, is_primary, "
                    "influence_tier, trend HAVING n > 1)").fetchone()[0]
            finally:
                win.close()
                win.deleteLater()
                app.processEvents()
                win.db.close()
    finally:
        sys.excepthook = old_hook
        unblock_network()
        release_errors()

    for (area, text), n in errs.items():
        findings.append({"area": area, "check": "replay", "severity": "replay",
                         "text": text if n == 1 else f"{text} (x{n})"})
    logs = Counter((_record_area(r, repo_root, areas),
                    ("dedupe pass: " if i >= n_rec1 else "") + f"{r.name}: {r.getMessage()}")
                   for i, r in enumerate(records))
    for (area, text), n in logs.items():
        findings.append({"area": area, "check": "replay", "severity": "replay",
                         "text": text if n == 1 else f"{text} (x{n})"})

    checks = []
    if seen["_bio"]:
        checks.append((EXOBIO, "exobio_bio_bodies_unpredicted"))
    if seen["_analyse"]:
        checks.append((EXOBIO, "exobio_sampled_misses"))
    if seen["MissionCompleted"]:
        checks.append((MISSIONS, "mission_completion_duplicates"))
    for area, key in checks:
        now, base = misses[key], baselines.get(key, 0)
        if now > base:
            findings.append({"area": area, "check": "replay", "severity": "replay",
                             "text": f"{key} now {now}, baseline {base}"})
        elif now < base:
            findings.append({"area": area, "check": "replay", "severity": "info",
                             "text": f"better than baseline: {key} now {now}, baseline {base}"})
    if seen["Market"]:
        findings.append({"area": TRADE, "check": "replay", "severity": "info",
                         "text": "trade check not checkable from journals: market rows are saved from "
                                 "Market.json (live only), not from the Market event"})
    if seen["_factions"] and not after1.get("faction_snapshots"):
        findings.append({"area": BGS, "check": "replay", "severity": "replay",
                         "text": "FSDJump/Location with Factions replayed but faction_snapshots is empty"})
    if seen["ColonisationConstructionDepot"] and not after1.get("colonisation_depots"):
        findings.append({"area": COLONY, "check": "replay", "severity": "replay",
                         "text": "ColonisationConstructionDepot replayed but colonisation_depots is empty"})

    allowed = set(baselines.get("dedupe_allowed_tables", []))
    for table, a in after1.items():
        b = after2.get(table, a)
        if b != a and table not in allowed:
            findings.append({"area": _table_area(table, areas), "check": "replay", "severity": "replay",
                             "text": f"dedupe: {table} grew {a} -> {b} on second pass"})

    if bad:
        findings.append({"area": "Other", "check": "replay", "severity": "info",
                         "text": f"{len(bad)} bad JSON line(s) skipped: "
                                 + ", ".join(f"{f}:{n}" for f, n in bad[:5])})
    findings.append({"area": "Other", "check": "replay", "severity": "info",
                     "text": blocked_note("replay", counter)})

    problems = Counter(f["area"] for f in findings if f["severity"] == "replay")
    cells = {a: f"{problems[a]} problems" if problems[a] else "ok" for a in AREA_ORDER}
    return {"cells": cells, "findings": findings, "seconds": time.time() - t0, "stats": stats}
