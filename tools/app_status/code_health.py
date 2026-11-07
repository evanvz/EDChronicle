import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from tools.app_status.areas import AREAS_PATH, AREA_ORDER, area_of, load_json

CAP = 50
TOOL_TIMEOUT_S = 600
WHITELIST = Path(__file__).parent / "vulture_whitelist.py"
LIVE_FILES = ["edc/core/event_engine.py", "edc/engine/handlers/*.py"]
_VULTURE = re.compile(r"^(.+?):(\d+): (.+)$")
_EVENT_LINE = re.compile(r"\bname\s*(?:==|in\b)")
_EVENT_NAME = re.compile(r'"([A-Z][A-Za-z0-9]+)"')


def _rel(path, repo_root=None):
    p = str(path).replace("\\", "/")
    if repo_root is not None:
        root = str(Path(repo_root)).replace("\\", "/").rstrip("/") + "/"
        if p.startswith(root):
            p = p[len(root):]
    return p


def parse_vulture(text):
    out = []
    for line in text.splitlines():
        m = _VULTURE.match(line.strip())
        if m:
            out.append((_rel(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def parse_ruff_json(text):
    return [(_rel(d["filename"]), d["location"]["row"], d["code"])
            for d in json.loads(text or "[]")]


def parse_pylint_dups(text):
    """Return one list of dotted module names per R0801 block."""
    out, mods = [], None
    for line in text.splitlines():
        if "R0801" in line:
            if mods:
                out.append(mods)
            mods = []
        elif mods is not None and line.startswith("=="):
            mods.append(line[2:].split(":[")[0])
    if mods:
        out.append(mods)
    return out


def _event_names(src):
    names = set()
    for line in src.splitlines():
        if _EVENT_LINE.search(line):
            names.update(_EVENT_NAME.findall(line))
    return names


def dual_path_events(importer_src, live_srcs):
    live = set()
    for s in live_srcs:
        live |= _event_names(s)
    return sorted(_event_names(importer_src) & live)


def _method_source(src, name):
    m = re.search(rf"^( *)def {name}\(", src, re.M)
    if not m:
        return ""
    lines = src[m.start():].splitlines()
    ind = len(m.group(1))
    body = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= ind:
            break
        body.append(ln)
    return "\n".join(body)


def _live_sources(repo_root):
    srcs = []
    for g in LIVE_FILES:
        for p in sorted(Path(repo_root).glob(g)):
            srcs.append(p.read_text(encoding="utf-8", errors="replace"))
    mw = Path(repo_root) / "edc/ui/main_window.py"
    if mw.exists():
        srcs.append(_method_source(mw.read_text(encoding="utf-8", errors="replace"), "_on_event"))
    return srcs


def _run(repo_root, module, args):
    """Return (stdout, error). error is a short string when the tool is missing or crashed."""
    try:
        ver = subprocess.run([sys.executable, "-m", module, "--version"], cwd=repo_root,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{module} not runnable ({e})"
    if ver.returncode != 0:
        return None, f"{module} not installed (pip install -r requirements-dev.txt)"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        r = subprocess.run([sys.executable, "-m", module, *args], cwd=repo_root, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TOOL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"{module} timed out after {TOOL_TIMEOUT_S}s"
    except OSError as e:
        return None, f"{module} failed to run ({e})"
    return r.stdout, None


def _to_file(repo_root, dotted):
    rel = dotted.replace(".", "/") + ".py"
    for base in ("edc", ".", "persistence"):
        if (Path(repo_root) / base / rel).exists():
            return (Path(base) / rel).as_posix().removeprefix("./")
    return rel


def check_code_health(repo_root, coverage):
    t0 = time.time()
    repo_root = Path(repo_root)
    areas = load_json(AREAS_PATH)
    findings, secs = [], {}
    counts = {a: {"U": 0, "D": 0} for a in AREA_ORDER}

    def add(area, severity, text):
        findings.append({"area": area, "check": "code_health", "severity": severity, "text": text})

    def report(tool, label, hits):
        by_area = {}
        for area, text in hits:
            by_area.setdefault(area, []).append(text)
        for area, texts in by_area.items():
            for t in texts[:CAP]:
                add(area, "suspect", t)
            if len(texts) > CAP:
                add(area, "suspect", f"{tool}: {len(texts)} {label} (first {CAP} listed)")
        return {a: len(t) for a, t in by_area.items()}

    def area_for(path):
        return area_of(_rel(path, repo_root), "module", areas)

    def timed(module, args):
        t = time.time()
        out, err = _run(repo_root, module, args)
        secs[module] = round(time.time() - t, 1)
        if err:
            add("Other", "info", err)
        return out

    out = timed("vulture", ["edc", "persistence", str(WHITELIST), "--min-confidence", "60"])
    if out is not None:
        hits = [(area_for(p), f"unused? {p}:{ln} {msg}") for p, ln, msg in parse_vulture(out)]
        for a, n in report("vulture", "unused?", hits).items():
            counts[a]["U"] += n

    out = timed("ruff", ["check", "edc", "persistence", "--select", "F401,F841,F811",
                         "--output-format", "json"])
    if out is not None:
        try:
            hits = [(area_for(p), f"ruff {code} {p}:{ln}") for p, ln, code in parse_ruff_json(out)]
        except (ValueError, KeyError) as e:
            hits = []
            add("Other", "info", f"ruff output unreadable ({e})")
        for a, n in report("ruff", "findings", hits).items():
            counts[a]["U"] += n

    out = timed("pylint", ["edc", "persistence", "--disable=all", "--enable=duplicate-code",
                           "--min-similarity-lines=8"])
    if out is not None:
        hits = []
        for mods in parse_pylint_dups(out):
            files = [_to_file(repo_root, m) for m in mods]
            hits.append((area_for(files[0]), "duplicate? " + " <-> ".join(files)))
        for a, n in report("pylint", "duplicate?", hits).items():
            counts[a]["D"] += n

    imp = repo_root / "edc/core/journal_importer.py"
    if imp.exists():
        both = dual_path_events(imp.read_text(encoding="utf-8", errors="replace"),
                                _live_sources(repo_root))
        if both:
            add("Other", "suspect", "handled by importer and live path: " + ", ".join(both))

    cells = {}
    for a in AREA_ORDER:
        parts = [f"{counts[a]['U']} unused?", f"{counts[a]['D']} dup?"]
        if coverage and a in coverage:
            parts.append(f"{coverage[a]:.0f}% covered")
        cells[a] = " / ".join(parts)
    return {"cells": cells, "findings": findings, "seconds": round(time.time() - t0, 1),
            "tool_seconds": secs}
