import json
from pathlib import Path

from tools.app_status.replay import journal_files, run_replay

ROOT = Path(__file__).parent.parent

_SYS = {"StarSystem": "Synth Sector AB-C d1", "SystemAddress": 1234567}
_BODY = "Synth Sector AB-C d1 1 a"


def write_synthetic_journal(dir: Path) -> Path:
    events = [
        {"timestamp": "2026-11-01T10:00:00Z", "event": "Fileheader", "part": 1, "language": "English/UK",
         "Odyssey": True, "gameversion": "4.2.0.0", "build": "r1 "},
        {"timestamp": "2026-11-01T10:01:00Z", "event": "FSDJump", **_SYS, "StarPos": [1.0, 2.0, 3.0],
         "SystemAllegiance": "", "Population": 0, "JumpDist": 10.0, "FuelUsed": 1.0, "FuelLevel": 30.0},
        {"timestamp": "2026-11-01T10:02:00Z", "event": "Scan", "ScanType": "Detailed", "BodyName": _BODY,
         "BodyID": 5, **_SYS, "DistanceFromArrivalLS": 500.0, "PlanetClass": "Rocky body", "Landable": True,
         "TerraformState": "", "Atmosphere": "thin carbon dioxide atmosphere", "AtmosphereType": "CarbonDioxide",
         "AtmosphereComposition": [{"Name": "CarbonDioxide", "Percent": 100.0}], "Volcanism": "",
         "SurfaceGravity": 9.797759, "SurfaceTemperature": 180.0, "SurfacePressure": 3000.0,
         "WasDiscovered": False, "WasMapped": False},
        {"timestamp": "2026-11-01T10:03:00Z", "event": "FSSBodySignals", "BodyName": _BODY, "BodyID": 5,
         "SystemAddress": _SYS["SystemAddress"],
         "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 4}]},
    ]
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / "Journal.2026-11-01T100000.01.log"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _sev(res, sev):
    return [f for f in res["findings"] if f["severity"] == sev]


def test_no_journal_dir_fails_loudly():
    res = run_replay(ROOT, None, 7)
    assert any("no journal dir" in f["text"] for f in _sev(res, "replay"))


def test_synthetic_replay_is_clean(tmp_path):
    write_synthetic_journal(tmp_path / "j")
    res = run_replay(ROOT, str(tmp_path / "j"), 7)
    assert _sev(res, "replay") == []
    assert res["stats"]["events"] == 4


def test_bio_signal_before_scan_is_checked_at_the_scan(tmp_path):
    # The game writes FSSBodySignals before the body's Scan.
    p = write_synthetic_journal(tmp_path / "j")
    head, jump, scan, signals = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    p.write_text("".join(json.dumps(e) + "\n" for e in (head, jump, signals, scan)), encoding="utf-8")
    assert _sev(run_replay(ROOT, str(tmp_path / "j"), 7), "replay") == []

    del scan["SurfaceGravity"]  # unpredictable body: the deferred check must still count it
    p.write_text("".join(json.dumps(e) + "\n" for e in (head, jump, signals, scan)), encoding="utf-8")
    res = run_replay(ROOT, str(tmp_path / "j"), 7)
    assert any("exobio_bio_bodies_unpredicted now 1" in f["text"] for f in _sev(res, "replay"))


def test_truncated_last_line_is_counted_not_raised(tmp_path):
    p = write_synthetic_journal(tmp_path / "j")
    with p.open("a", encoding="utf-8") as f:
        f.write('{"timestamp": "2026-11-01T10:04:00Z", "event": "Sc')
    res = run_replay(ROOT, str(tmp_path / "j"), 7)
    assert any("1" in f["text"] and "bad" in f["text"] for f in _sev(res, "info"))


def test_journal_files_days_window(tmp_path):
    for name in ("Journal.2026-11-01T100000.01.log", "Journal.2026-10-22T100000.01.log",
                 "Journal.2026-10-28T100000.01.log"):
        (tmp_path / name).write_text("", encoding="utf-8")
    names = [p.name for p in journal_files(tmp_path, 7)]
    assert names == ["Journal.2026-10-28T100000.01.log", "Journal.2026-11-01T100000.01.log"]
    assert len(journal_files(tmp_path, None)) == 3
