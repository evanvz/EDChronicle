import json
import sqlite3
from datetime import datetime, timedelta, timezone

from tools.app_status.freshness import (
    check_freshness, copy_db, newest_event_time, run_freshness, scan_logs)

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def _areas(table="t", col="ts", clock="play", days=14):
    return {"A": {"modules": ["edc/core/x.py"], "fresh": [
        {"table": table, "column": col, "max_days": days, "clock": clock}]}}


def _db(path, ts):
    c = sqlite3.connect(path)
    c.execute("create table t(ts text)")
    c.execute("insert into t values (?)", (ts,))
    c.commit()
    c.close()
    return path


def test_play_clock_stale_and_ok(tmp_path):
    old = (NOW - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = check_freshness(_db(tmp_path / "a.db", old), _areas(), NOW, NOW + timedelta(days=100))
    assert r["findings"][0]["severity"] == "stale" and r["cells"]["A"].startswith("STALE")
    new = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
    r = check_freshness(_db(tmp_path / "b.db", new), _areas(), NOW, NOW)
    assert not r["findings"] and r["cells"]["A"] == "2026-11-05"


def test_missing_table_and_unparseable(tmp_path):
    r = check_freshness(_db(tmp_path / "a.db", "junk"), _areas(table="nope"), NOW, NOW)
    assert r["findings"][0]["severity"] == "info"
    r = check_freshness(tmp_path / "a.db", _areas(), NOW, NOW)
    assert r["findings"][0]["severity"] == "info"


def test_copy_db_wal_with_open_writer(tmp_path):
    src = tmp_path / "w.db"
    w = sqlite3.connect(src)
    w.execute("pragma journal_mode=wal")
    w.execute("create table t(ts text)")
    w.execute("insert into t values ('2026-11-01')")
    w.commit()
    w.execute("insert into t values ('2026-11-02')")
    w.commit()
    dst = tmp_path / "c.db"
    copy_db(src, dst)
    c = sqlite3.connect(dst)
    assert c.execute("select count(*) from t").fetchone()[0] == 2
    c.close()
    w.close()


def test_newest_event_and_missing_db(tmp_path):
    jd = tmp_path / "j"
    jd.mkdir()
    good = json.dumps({"timestamp": "2026-11-06T12:05:00Z", "event": "X"})
    (jd / "Journal.2026-11-06T120000.01.log").write_text(good + '\n{"timestamp": "20', encoding="utf-8")
    assert newest_event_time(jd) == datetime(2026, 11, 6, 12, 5, tzinfo=timezone.utc)
    assert newest_event_time(tmp_path / "empty") is None
    r = run_freshness(tmp_path / "none.db", jd, {}, NOW)
    assert r["findings"][0]["severity"] == "stale" and r["findings"][0]["area"] == "Other"


def test_scan_logs(tmp_path):
    (tmp_path / "edc_2026-11-06_101641.log").write_text(
        "2026-11-06 10:16:41,000 [INFO] [edc.core.x] hello\n"
        "2026-11-06 10:16:42,000 [ERROR] [edc.core.x] boom\n", encoding="utf-8")
    r = scan_logs(tmp_path, 7, _areas(), NOW)
    assert r["cells"] == {"A": "1 errors"}
    assert r["findings"][0]["severity"] == "replay" and "boom" in r["findings"][0]["text"]
