import inspect
import logging
import os
import shutil
import sys
import socket
import time
import traceback
from collections import Counter
from pathlib import Path

from tools.app_status.areas import AREAS_PATH, AREA_ORDER, area_of, area_of_logger, load_json

BLOCK_MSG = "app_status: outbound blocked"
_WINDOWS = []  # keep windows (and their QThreads) alive until process exit
_ORIG = {}
_HANDLER = []


def _log_uncaught(tp, val, tb):
    logging.getLogger("app_status").error("uncaught %s: %s", tp.__name__, val, exc_info=(tp, val, tb))


class OutboundBlocked(OSError):
    pass


def _loopback(host) -> bool:
    h = host.decode() if isinstance(host, bytes) else str(host)
    return h.lower() in ("localhost", "::1") or h.startswith("127.")


def block_network() -> dict:
    unblock_network()
    counter = {"attempts": 0, "hosts": set()}
    orig = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection, "getaddrinfo": socket.getaddrinfo}

    def _deny(addr):
        counter["attempts"] += 1
        counter["hosts"].add(str(addr[0]) if isinstance(addr, tuple) else str(addr))
        raise OutboundBlocked(f"{BLOCK_MSG} {addr}")

    def _host(addr):
        return addr[0] if isinstance(addr, tuple) else addr

    def _getaddrinfo(host, *a, **k):
        if host is None or _loopback(host):
            return orig["getaddrinfo"](host, *a, **k)
        return _deny(host)

    _ORIG.update(orig)
    socket.socket.connect = lambda self, addr: (
        orig["connect"](self, addr) if _loopback(_host(addr)) else _deny(addr))
    socket.socket.connect_ex = lambda self, addr: (
        orig["connect_ex"](self, addr) if _loopback(_host(addr)) else _deny(addr))
    socket.create_connection = lambda address, *a, **k: (
        orig["create_connection"](address, *a, **k) if _loopback(_host(address)) else _deny(address))
    socket.getaddrinfo = _getaddrinfo
    return counter


def unblock_network() -> None:
    if _ORIG:
        socket.socket.connect = _ORIG["connect"]
        socket.socket.connect_ex = _ORIG["connect_ex"]
        socket.create_connection = _ORIG["create_connection"]
        socket.getaddrinfo = _ORIG["getaddrinfo"]
        _ORIG.clear()


def blocked_note(check: str, counter: dict) -> str:
    hosts = sorted(counter["hosts"])[:10]
    return (f"{check}: outbound senders disabled; {counter['attempts']} connection attempts blocked"
            + (f" ({', '.join(hosts)})" if hosts else ""))


def make_app_dir(repo_root: Path, tmp: Path) -> Path:
    settings = Path(tmp) / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    for f in (Path(repo_root) / "settings").glob("*.json"):
        if f.name != "settings.json":
            shutil.copy2(f, settings / f.name)
    return Path(tmp)


def build_window(app_dir: Path, journal_dir):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    from edc.config import ConfigStore
    from edc.ui.main_window import MainWindow

    sys.excepthook = _log_uncaught  # PyQt aborts the process on an unhandled slot exception
    app = QApplication.instance() or QApplication([])
    store = ConfigStore(app_dir)
    cfg = store.load()
    cfg.journal_dir = journal_dir
    cfg.eddn_contribute_enabled = False
    cfg.raven_push_enabled = False
    cfg.edsm_push_enabled = False
    cfg.tts_enabled = False
    cfg.comms_enabled = False
    cfg.voice_commands_enabled = False
    cfg.push_to_talk_enabled = False
    win = MainWindow(store, cfg, auto_start=False)
    _WINDOWS.append(win)
    return app, win, store


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        exc = record.exc_info[1] if record.exc_info else None
        if BLOCK_MSG not in record.getMessage() + str(exc or ""):
            self.records.append(record)


def capture_errors() -> list:
    h = _Collector()
    logging.getLogger().addHandler(h)
    _HANDLER.append(h)
    return h.records


def release_errors() -> None:
    while _HANDLER:
        logging.getLogger().removeHandler(_HANDLER.pop())


def _area_from_exc(exc, repo_root: Path, areas: dict) -> str:
    edc_dir = (Path(repo_root) / "edc").resolve()
    for fr in reversed(traceback.extract_tb(exc.__traceback__)):
        p = Path(fr.filename).resolve()
        if edc_dir in p.parents:
            return area_of(p.relative_to(Path(repo_root).resolve()).as_posix(), "module", areas)
    return "Other"


def _refresh_methods(win):
    for name in sorted(dir(win)):
        if not name.startswith("_refresh_"):
            continue
        fn = getattr(win, name)
        if not callable(fn):
            continue
        try:
            params = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            continue
        if all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in params):
            yield name, fn


def check_app_start(repo_root: Path) -> dict:
    import tempfile
    t0 = time.time()
    areas = load_json(AREAS_PATH)
    findings = []
    counter = block_network()
    records = capture_errors()
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app_dir = make_app_dir(repo_root, Path(tmp))
            try:
                app, win, _ = build_window(app_dir, None)
                assert Path(win.db.db_path).resolve().is_relative_to(app_dir.resolve())
            except Exception as e:
                findings.append({"area": _area_from_exc(e, repo_root, areas), "check": "app start",
                                 "severity": "start",
                                 "text": f"window build failed: {type(e).__name__}: {e}"})
            else:
                for name, fn in _refresh_methods(win):
                    try:
                        fn()
                    except Exception as e:
                        findings.append({"area": _area_from_exc(e, repo_root, areas), "check": "app start",
                                         "severity": "start",
                                         "text": f"{name} raised {type(e).__name__}: {e}"})
                app.processEvents()
                win.close()
                win.deleteLater()
                app.processEvents()
                win.db.close()
    finally:
        unblock_network()
        release_errors()
    logs = Counter((area_of_logger(r.name, repo_root, areas), f"{r.name}: {r.getMessage()}") for r in records)
    for (area, text), n in logs.items():
        findings.append({"area": area, "check": "app start", "severity": "start",
                         "text": text if n == 1 else f"{text} (x{n})"})
    bad = {f["area"] for f in findings}
    findings.append({"area": "Other", "check": "app start", "severity": "info",
                     "text": blocked_note("app start", counter)})
    return {"cells": {a: "error" if a in bad else "ok" for a in AREA_ORDER},
            "findings": findings, "seconds": time.time() - t0}
