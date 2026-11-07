# App Status Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`python -m tools.app_status`) that checks EDChronicle's health and writes a dated Markdown + JSON report. The report has rows per feature area, five columns, an attention list, and a comparison with the previous report.

**Architecture:** A dev-only package `tools/app_status/` with one module per check. Each check returns the same `CheckResult` dict. `report.py` merges them into Markdown + JSON, and `__main__.py` runs the checks for the chosen mode.

The live DB writes happen inside `MainWindow._on_event` (`edc/ui/main_window.py`), so replay must drive a real headless `MainWindow`. It does this inside a sandbox: a temp app dir with a fresh DB, Qt offscreen, and all sockets blocked.

**Tech Stack:** Python 3 / PyQt6 (existing `.venv`), pytest, stdlib `sqlite3`, `subprocess`, `socket`, `json`. The dev-only tools are pytest-cov, vulture, ruff and pylint (duplicate-code only).

**Spec:** `docs/superpowers/specs/2026-11-07-app-status-report-design.md` (approved 2026-11-07).

## Global Constraints

- Never write to the real `data/edhelper.db`, `settings/`, or journals.
  - The real DB is read only through a `sqlite3` backup copy, made with `Connection.backup`, into a `tempfile.TemporaryDirectory()`.
  - `network_cache.db` is never copied.
- Nothing leaves the machine during replay or the app-start check. Sockets are blocked, and the report states "outbound senders disabled; N connection attempts blocked".
- Never copy the real `settings/settings.json` into the sandbox (it holds API keys). Copy only the shipped `settings/*.json` assets, excluding `settings.json`.
- Report only: no check changes code, config or data.
- Dev tools go in a new `requirements-dev.txt`. `requirements.txt` stays untouched.
- Paths come from `ConfigStore(default_app_dir())` / `cfg.journal_dir`; nothing is hard-coded to one laptop.
- Windows, PS 5.1/7, project `.venv`. Headless Qt needs `QT_QPA_PLATFORM=offscreen`, set before any PyQt import.
- Reports go to `reports/app_status_YYYY-MM-DD.md` + `.json` (same stem). `reports/` is git-ignored. A second run on the same day overwrites that day's pair.
- Exit code 1 if any finding has severity `start`, `test`, `replay` or `stale`. Otherwise 0. The report is always written before exit.
- Modes:
  - **quick** (default): tests without coverage, 7-day replay, app start, log scan, freshness.
  - **full** (`--full`): adds coverage, code health, a 30-day replay and the importer comparison.
  - `--all-journals`: replays every journal (full mode only).
  - `--skip-tests`: skips pytest (used by this package's own tests).
- Python style: simple module-level functions, no classes unless needed.
- Run the full test suite with `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider` (offscreen). Two failures are known and pre-existing: `test_eddatahub_ticks::test_hub_ticks_parsed_and_offline_is_none` and `test_expansion_forecast_repo::test_presence_has_first_and_latest_reading`.

## Shared shapes (all tasks)

```python
Finding = {"area": str, "check": str, "severity": str, "text": str}
# severity, worst first: "start" > "test" > "replay" > "stale" > "suspect" > "info"
CheckResult = {"cells": {area: str}, "findings": [Finding], "seconds": float}
```

`cells` is the text shown in that check's column for each area. An area missing from `cells` shows as `—`.

## Review Focus

1. **The app is running during the check.** The DB is in WAL mode and the current journal's last line may be half-written. The backup copy must still succeed, and bad JSON lines are skipped and counted, not raised. *(Task 4, Task 6 tests)*
2. **No journal dir configured or found** (fresh laptop). Replay reports a `replay` finding "replay not run: no journal dir", which makes the report fail. It must never pass silently. *(Task 4 test)*
3. **The checker's own tests are inside the suite it runs.** Its tests must never launch pytest or a real replay recursively. The CLI test uses `--skip-tests` and a synthetic journal dir. *(Task 8 test)*
4. **An outbound attempt during replay** is blocked and counted, and is not reported as an app error. *(Task 3 test)*
5. **First run, or a corrupt previous JSON.** The comparison says "first report" (or "previous report unreadable") and does not crash. *(Task 8 test)*

---

### Task 1: Area map, baselines, live-confirmed file, dev requirements

**Files:**
- Create: `tools/app_status/__init__.py` (empty), `tools/app_status/areas.py`, `tools/app_status/areas.json`, `tools/app_status/baselines.json`, `tools/app_status/live_confirmed.json`, `requirements-dev.txt`
- Modify: `.gitignore` (add `reports/`)
- Test: `tests/test_app_status_areas.py`

**Interfaces:**
- Produces:
  - `AREAS_PATH`, `BASELINES_PATH`, `LIVE_CONFIRMED_PATH: Path`
  - `load_json(path: Path) -> dict`
  - `area_of(rel_path: str, kind: str, areas: dict) -> str`: `kind` is `"module"` or `"test"`. Returns the first matching area name, else `"Other"`.
  - `mapping_problems(repo_root: Path, areas: dict) -> dict`: returns `{"unmapped": [rel paths], "ambiguous": [rel paths]}`. It covers every `edc/**/*.py`, `persistence/*.py` and `tests/test_*.py`. Excluded: `__init__.py` and anything under `__pycache__`.
  - `AREA_ORDER: list[str]`: the spec's area order, ending with `"Other"`.

**`areas.json` shape:**

```json
{"Overview/HUD": {"modules": ["edc/ui/panels/overview_panel.py", "..."], "tests": ["tests/test_overview*.py"],
  "fresh": [{"table": "systems", "column": "last_visit", "max_days": 14, "clock": "play"}]}, "...": {}}
```

- Areas, exact names and order:
  - Overview/HUD
  - BGS & factions
  - Powerplay
  - Colonisation & system planner
  - Exploration & exobiology
  - Trade, markets & routes
  - Mining
  - Missions
  - Megaships
  - Engineering & materials
  - Combat scanners
  - Squadron
  - EDDN sending
  - EDDataHub link
  - Raven Colonial & EDSM push
  - Voice
  - Other
- Globs use `fnmatch` on forward-slash paths relative to the repo root.
- `"Other"` has no globs. It is the catch-all.
- `clock` is `"play"` (measured against the newest journal event) or `"now"` (for EDDataHub/tick tables).
- The implementer fills the globs and `fresh` entries by reading module names and the table list in `persistence/`. Tables named `net.*` are not allowed in `fresh`.
- Done means `mapping_problems` returns empty `ambiguous` and an `unmapped` list of only deliberately uncategorised files. Each of those gets added to an `"Other"` globs list, so `unmapped` ends up empty.

**`baselines.json` (exact start values):**

```json
{"replay_exceptions": 0, "exobio_sampled_misses": 3, "exobio_bio_bodies_unpredicted": 0,
 "mission_completion_duplicates": 0, "dedupe_allowed_tables": []}
```

**`live_confirmed.json`:** `{area: {"date": "YYYY-MM-DD" | null, "note": str}}` for every area. Start values:
- Exploration & exobiology: `null`, note "merged dffb398, awaiting live check".
- Raven Colonial & EDSM push: `"2026-11-02"`, note "EDSM live; Raven depot pending".
- Every other area: `null`, note `""`.

**`requirements-dev.txt`:** `-r requirements.txt`, then `pytest`, `pytest-cov`, `vulture`, `ruff`, `pylint`. No pins: install the current versions and record the installed versions in the task report.

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
from tools.app_status.areas import AREAS_PATH, AREA_ORDER, area_of, load_json, mapping_problems

ROOT = Path(__file__).parent.parent

def test_unknown_module_falls_to_other():
    assert area_of("edc/core/nope_xyz.py", "module", {"A": {"modules": ["edc/ui/*"], "tests": []}}) == "Other"

def test_first_matching_area_wins():
    areas = {"A": {"modules": ["edc/core/exo_*.py"], "tests": []}, "B": {"modules": ["edc/core/*"], "tests": []}}
    assert area_of("edc/core/exo_predictor.py", "module", areas) == "A"

def test_real_map_has_no_gaps_or_overlaps():
    probs = mapping_problems(ROOT, load_json(AREAS_PATH))
    assert probs == {"unmapped": [], "ambiguous": []}

def test_area_order_matches_map_and_ends_with_other():
    assert AREA_ORDER[-1] == "Other" and set(AREA_ORDER) == set(load_json(AREAS_PATH))

def test_reports_dir_is_ignored():
    assert "reports/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_app_status_areas.py -q -p no:cacheprovider`. Expected: FAIL (`ModuleNotFoundError: tools.app_status`).
- [ ] **Step 3: Implement** `areas.py` and the four data files as specified. Then `pip install -r requirements-dev.txt` into `.venv`.
- [ ] **Step 4: Run** the same test file. Expected: PASS.
- [ ] **Step 5: Commit** `feat: app status area map and baselines`

---

### Task 2: Tests check (per-area pytest results, coverage in full mode)

**Files:** Create `tools/app_status/check_tests.py`. Test: `tests/test_app_status_tests_check.py`

**Interfaces:**
- Consumes: `area_of`, `load_json`, `AREAS_PATH`.
- Produces: `run_tests(repo_root: Path, full: bool) -> CheckResult`, plus `parse_junit(xml_path: Path) -> dict[str, dict]`, which maps a test file rel path to `{"passed": int, "failed": int, "errors": int}`.
- `run_tests` runs `sys.executable -m pytest tests/ -q -p no:cacheprovider --junitxml=<tmp>/j.xml` with `QT_QPA_PLATFORM=offscreen` in its env.
  - In full mode, add `--cov=edc --cov=persistence --cov-report=json:<tmp>/cov.json`. Save the coverage JSON into the result as `result["coverage"] = {area: percent_lines_covered}` for Task 7.
- Cell per area: `"pass 42"`, `"fail 2/42"`, or `"none"` when there are no test files.
- Every failing test gives a `test` finding with text `"<nodeid>: <first line of message>"`.
- **Known failures:** `KNOWN_FAILURES` is a set holding the two pre-existing failing node ids from Global Constraints. These give an `info` finding, not `test`, and the cell shows `"pass 41 (+1 known)"`.

- [ ] **Step 1: Failing tests.** Write a tiny junit XML fixture in `tmp_path`: one pass and one failure in `tests/test_overview_x.py`. Assert that:
  - `parse_junit` gives `{"tests/test_overview_x.py": {"passed": 1, "failed": 1, "errors": 0}}`;
  - `cells_from_counts` (a pure helper with signature `cells_from_counts(counts, areas, known_failed: dict[str, int]) -> dict[str, str]`) gives `"fail 1/2"` for the owning area;
  - a known failure yields severity `"info"`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: app status tests check`

---

### Task 3: Sandbox and app-start check

**Files:** Create `tools/app_status/sandbox.py`. Test: `tests/test_app_status_sandbox.py`

**Interfaces:**
- Produces:
  - `class OutboundBlocked(OSError)`: its message always starts with `"app_status: outbound blocked"`.
  - `block_network() -> dict`. Patches `socket.socket.connect`, `socket.socket.connect_ex` and `socket.create_connection` to raise `OutboundBlocked`. Returns a live counter dict `{"attempts": int, "hosts": set[str]}`.
  - `make_app_dir(repo_root: Path, tmp: Path) -> Path`. Creates `tmp/settings`. Copies every `repo_root/settings/*.json` except `settings.json`. Copies `repo_root/assets` only if `MainWindow` needs it to build.
  - `build_window(app_dir: Path, journal_dir: str | None)`. Returns `(app, win, store)`.
    - It sets `QT_QPA_PLATFORM=offscreen` and uses `ConfigStore(app_dir)` and `store.load()`.
    - It forces `cfg.journal_dir = journal_dir`, `eddn_contribute_enabled = False`, `raven_push_enabled = False`, `edsm_push_enabled = False`, and turns voice off (find the cfg flag).
    - It then constructs `MainWindow(store, cfg, auto_start=False)`.
  - `capture_errors() -> list[logging.LogRecord]`. Attaches a root handler that keeps ERROR+ records, excluding any whose message contains `"app_status: outbound blocked"` (those are counted, not errors).
  - `check_app_start(repo_root: Path) -> CheckResult`. Builds the window in a sandbox, then calls every `_refresh_*` method on `win` that takes no required args, once each, inside try/except.
    - Cells: `"ok"` per area, or `"error"`.
    - Findings: severity `start` for a build failure or any refresh exception. The area comes from the innermost `edc/` frame in the traceback, via `area_of`.
    - It adds an `info` finding "outbound senders disabled; N connection attempts blocked".

- [ ] **Step 1: Failing tests:**

```python
def test_block_network_counts_and_raises():
    counter = block_network()
    with pytest.raises(OutboundBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
    assert counter["attempts"] == 1

def test_sandbox_never_copies_user_settings(tmp_path):
    app_dir = make_app_dir(ROOT, tmp_path)
    assert not (app_dir / "settings" / "settings.json").exists()
    assert (app_dir / "settings" / "exo_values.json").exists()

def test_blocked_records_are_not_errors():
    recs = capture_errors()
    logging.getLogger("edc.core.galnet_news").error("fetch failed: app_status: outbound blocked example.com")
    logging.getLogger("edc.core.galnet_news").error("real failure")
    assert [r.getMessage() for r in recs] == ["real failure"]
```

  Restore the patched socket functions and detach the handler in teardown with a fixture, so the rest of the suite is unaffected.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `MainWindow` writes its DB to `app_dir/data/edhelper.db`, a fresh DB inside the temp dir. Confirm that by asserting `win.db.db_path` is under `app_dir`.
- [ ] **Step 4: Run** the tests, then run `check_app_start(ROOT)` once by hand and paste its findings into the task report. Expected: no `start` findings, or real ones you list.
- [ ] **Step 5: Commit** `feat: app status sandbox and app-start check`

---

### Task 4: Journal replay, dedupe pass, sanity checks

**Files:** Create `tools/app_status/replay.py`. Test: `tests/test_app_status_replay.py`

**Interfaces:**
- Consumes: Task 3's `block_network`, `make_app_dir`, `build_window`, `capture_errors`, plus `area_of` and `load_json(BASELINES_PATH)`.
- Produces:
  - `journal_files(journal_dir: Path, days: int | None) -> list[Path]`. Returns `Journal.*.log` files sorted by name. With `days`, keep only files whose filename date is within `days` of the newest file's date. `None` means all files.
  - `read_events(path: Path, bad: list) -> Iterator[dict]`. Each line that isn't valid JSON appends `(path.name, line_no)` to `bad` and is skipped.
  - `table_counts(conn) -> dict[str, int]`. Counts every table in `main` and in `net`.
  - `run_replay(repo_root: Path, journal_dir: str | None, days: int | None) -> CheckResult`.

**Behaviour of `run_replay`:**
1. Journal dir is `None` or missing: return `cells={}` with a `replay` finding: area `"Other"`, text `"replay not run: no journal dir"`.
2. Build a sandbox window (Task 3). Pass 1: feed every event in order to `win._on_event(evt)`, and call `app.processEvents()` every 500 events.
   - Wrap each call in try/except. An exception gives a `replay` finding: the area comes from the innermost `edc/` frame, and the text is `"<event name>: <ExcType>: <msg>"`. Group identical texts as `"... (xN)"`.
   - ERROR+ log records from `capture_errors` give `replay` findings, with the area taken from the logger name.
   - Do NOT send `_BootstrapStart`. The live path must run as it does in play, so senders stay off through cfg flags and the socket block.
3. Sanity checks, observed during pass 1:
   - **Exobiology:**
     - After each `FSSBodySignals`/`SAASignalsFound` event carrying a Biological signal, the body name must be a key of `win._exo_predictions()`. Each miss counts towards `exobio_bio_bodies_unpredicted`.
     - After each `ScanOrganic` with `ScanType == "Analyse"`, the species must be in that body's prediction: `possible[genus]` names, `known`, or `sampled`. Each miss counts towards `exobio_sampled_misses`.
   - **Missions:** after the pass, count duplicate mission ids in `faction_mission_completions`, using whichever column holds the mission id. That gives `mission_completion_duplicates`.
   - **BGS / Colonisation:**
     - If any `FSDJump`/`Location` event with `Factions` was replayed, `faction_snapshots` must have rows.
     - If any `ColonisationConstructionDepot` event was replayed, `colonisation_depots` must have rows.
   - A failure is a `replay` finding.
   - Each check's count is compared with `baselines.json`: worse than baseline is `replay`, better is `info` ("better than baseline: X now N, baseline B").
4. Pass 2 (dedupe): record `table_counts` and feed the same events again. Every table whose count changed and that isn't listed in `dedupe_allowed_tables` gives a `replay` finding: `"dedupe: <table> grew A -> B on second pass"`.
5. Bad JSON lines give one `info` finding with the count.
6. Cells: `"ok"` per area with no `replay` findings, otherwise `"N problems"`.
7. `result["stats"]` holds the event count, the file count and the seconds for each pass.

- [ ] **Step 1: Failing tests.** Use a synthetic journal dir in `tmp_path`. One file holds a `Fileheader`, then an `FSDJump`, then a landable `Scan` (Rocky body, 1.0 g, 180 K, thin CO2 atmosphere) and an `FSSBodySignals` with a Biological count of 4 for the same body, all written inline in the test. Assert that:
  - `run_replay(ROOT, None, 7)` yields a `replay` finding containing `"no journal dir"`;
  - on the synthetic dir it yields no `replay` findings, and `stats["events"] == 4`;
  - a file with a truncated last line yields an `info` finding mentioning `1` bad line, and no exception;
  - `journal_files` with `days=7` drops a file dated 10 days before the newest.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Then do one real quick replay by hand: `run_replay(ROOT, cfg.journal_dir, 7)`. Put its findings, stats and seconds in the task report. Do not add tables to `dedupe_allowed_tables` yourself; list growing tables in the report for the controller to rule on.
- [ ] **Step 5: Commit** `feat: app status journal replay with dedupe and sanity checks`

---

### Task 5: Importer vs live-path comparison (full mode)

**Files:** Create `tools/app_status/importer_compare.py`. Test: `tests/test_app_status_importer_compare.py`

**Interfaces:**
- Consumes: `journal_files`, `table_counts`, Task 3's sandbox functions, and a live-path DB produced by `run_replay`.
  - To support that, Task 5 changes `run_replay` to accept `keep_db: Path | None = None`. When it's given, `run_replay` copies the pass-1 DB there before pass 2.
- Produces:
  - `compare_paths(repo_root: Path, journal_dir: str, days: int | None, live_db: Path) -> CheckResult`.
  - `diff_tables(live: sqlite3.Connection, imported: sqlite3.Connection, tables: list[str]) -> list[str]`.
- `compare_paths` runs `JournalImporter(journal_dir_subset, Repository(Database(tmp/"imp.db"))).import_all()` on the same file window. To give it the same window, copy the selected journal files into a temp dir and point the importer at that.
- The tables to compare are those both DBs have rows in. For each one, compare row counts and then the set of key-column tuples. The key is the table's primary key; if it has none, use all non-timestamp columns.
- Each difference gives a `suspect` finding in the area owning the table: `"import vs live: <table> live=N import=M, K rows differ (e.g. ...)"`.

- [ ] **Step 1: Failing test.** Build two in-memory DBs from `SCHEMA_SQL` and insert a differing `bodies` row. Assert that `diff_tables` reports `bodies`, and that identical DBs report `[]`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: app status importer vs live comparison`

---

### Task 6: Data freshness and log scan

**Files:** Create `tools/app_status/freshness.py`. Test: `tests/test_app_status_freshness.py`

**Interfaces:**
- Produces:
  - `copy_db(src: Path, dst: Path) -> None`. Uses `sqlite3.connect(src).backup(sqlite3.connect(dst))`, with no ATTACH, so `network_cache.db` is never touched.
  - `check_freshness(db_copy: Path, areas: dict, newest_event: datetime, now: datetime) -> CheckResult`.
  - `scan_logs(logs_dir: Path, days: int, areas: dict, now: datetime) -> CheckResult`.
- `check_freshness`: for each area's `fresh` entries, take `MAX(column)`. The age is measured against `newest_event` when `clock == "play"`, and against `now` when `clock == "now"`.
  - Older than `max_days`: a `stale` finding, `"<table>.<column> last <date>, <N> days before <play|now>"`.
  - Cell: `"<newest date>"` or `"STALE <date>"`.
  - A missing table or column gives an `info` finding, not a crash.
- `newest_event` is the timestamp of the last event in the newest journal file. Read only that file's tail.
- `scan_logs`: read `logs/edc_*.log` files from the last `days` (7) days, and count ERROR lines and Tracebacks per logger name. A logger maps to an area by turning the module path `edc.x.y` into `edc/x/y.py` and calling `area_of`.
  - Cell: `"N errors"` (or `"0"`).
  - Each logger with errors gives one `replay` finding with its count and its most frequent message.
  - Learn the log line format from a real file in `logs/`.

- [ ] **Step 1: Failing tests.**
  - Build a tiny DB in `tmp_path` with a table `t(ts TEXT)`. With a `play` threshold of 14 days, a row 20 days before `newest_event` is `stale`, and a row 2 days before is OK.
  - A missing table gives `info`.
  - Run `copy_db` on a WAL DB that has an open writer connection. It succeeds, and the copy has the rows.
  - `scan_logs` on a two-line fake log (format copied from a real one) counts 1 error for the right area.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, then run `check_freshness` once on a real copy and put the cells in the task report.
- [ ] **Step 5: Commit** `feat: app status data freshness and log scan`

---

### Task 7: Code health (full mode)

**Files:** Create `tools/app_status/code_health.py`. Test: `tests/test_app_status_code_health.py`

**Interfaces:**
- Consumes: `area_of`, and `coverage` from Task 2's result.
- Produces:
  - `check_code_health(repo_root: Path, coverage: dict[str, float] | None) -> CheckResult`.
  - Pure helpers, so the tests run without the tools: `parse_vulture(text) -> list[(path, line, msg)]`, `parse_ruff_json(text) -> list[(path, line, code)]`, `dual_path_events(importer_src: str, live_srcs: list[str]) -> list[str]`.
- Tools, run as subprocesses with `sys.executable -m ...`:
  - `vulture edc persistence --min-confidence 60`
  - `ruff check edc persistence --select F401,F841,F811 --output-format json`
  - `pylint edc persistence --disable=all --enable=duplicate-code --min-similarity-lines=8`
- Every hit is a `suspect` finding in the owning area. Its text starts `"unused?"`, `"ruff <code>"` or `"duplicate?"`.
- `dual_path_events` returns the journal event names handled in both paths:
  - **Importer path:** event-name string literals in `edc/core/journal_importer.py`'s dispatch, i.e. event names compared or mapped there.
  - **Live path:** the same in `edc/core/event_engine.py`, `edc/engine/handlers/*.py` and `MainWindow._on_event`.
  - It produces one `suspect` finding in "Other": `"handled by importer and live path: Scan, Docked, ..."`.
- Cell per area: `"U unused? / D dup? / C% covered"`, with coverage left out when `None`.
- A tool that isn't installed gives an `info` finding "vulture not installed (pip install -r requirements-dev.txt)", not a crash.

- [ ] **Step 1: Failing tests.**
  - `parse_vulture` on a two-line sample (copy the format from a real run) returns two tuples.
  - `dual_path_events('if name == "Scan": ...\n"Docked"', ['if name == "Scan":'])` returns `["Scan"]`.
  - A missing tool gives an `info` finding. Simulate this by monkeypatching `shutil.which` or the subprocess runner.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, then run `check_code_health(ROOT, None)` once and give the counts per area in the task report.
- [ ] **Step 5: Commit** `feat: app status code health suspects`

---

### Task 8: Report, comparison, CLI

**Files:** Create `tools/app_status/report.py` and `tools/app_status/__main__.py`. Test: `tests/test_app_status_report.py`

**Interfaces:**
- Consumes: every check's `CheckResult`, `AREA_ORDER`, `LIVE_CONFIRMED_PATH`, and `edc/version.py`'s version constant (read it to learn the name).
- Produces:
  - `build_report(results: dict[str, CheckResult], meta: dict, previous: dict | None, problems: dict) -> tuple[str, dict]` returns markdown and JSON.
  - `exit_code(report_json: dict) -> int`.
  - `load_previous(reports_dir: Path, today_stem: str) -> dict | None | str`. It returns the newest older JSON, `None` if there isn't one, or the string `"unreadable"` on a parse error.
  - `main(argv: list[str]) -> int`.
- `meta` holds the date, the mode, the app version, the git commit (`git rev-parse --short HEAD`, or `"unknown"`), the per-check seconds, the journal window, and the replay stats.

**Markdown layout:**
1. Title `# App Status Report — YYYY-MM-DD (quick|full)`.
2. A meta line, then `**Result: PASS**` or `**Result: FAIL (N must-fix)**`.
3. An `App start:` line.
4. The area table, with columns `Area | Tests | Replay | Data fresh | Code health | Last live-confirmed`, one row per `AREA_ORDER` entry.
   - Replay cell: the replay cell and the log scan cell joined with `"; "`.
   - Code health cell: `—` in quick mode.
   - Last live-confirmed: date or `never`, plus the note.
5. `## Needs attention` lists findings sorted by severity rank and then area order, with each line prefixed `[severity] Area:`. Severity `info` is listed separately under `## Notes`.
6. `## Since last report` gives the new and resolved findings. Match on `(area, check, text)` with any `(xN)` suffix stripped. When there's no previous report or it can't be read, show `first report` or `previous report unreadable`.
7. `## Mapping` lists unmapped and ambiguous files, or `ok`.

**JSON:** `{"meta":…, "results":…, "problems":…, "findings": [all findings], "exit_code": int}`.

**`main` behaviour:**
1. Set `QT_QPA_PLATFORM=offscreen` first.
2. Parse `--full`, `--all-journals`, `--skip-tests` and `--journal-dir PATH` (an override; it defaults to `cfg.journal_dir` from `ConfigStore(default_app_dir())`).
3. Quick mode runs tests (no coverage), app start, a 7-day replay, freshness on a temp backup copy of `<app_dir>/data/edhelper.db`, and a 7-day log scan.
4. Full mode adds coverage, a 30-day replay (`None` with `--all-journals`), the importer comparison and code health.
5. Each check runs inside try/except. A crashing check gives a finding in "Other": severity `start` for app start, `test` for tests, otherwise `replay`, with text `"check <name> crashed: <exc>"`.
6. Write `reports/app_status_<date>.md` and `.json`, print the markdown path and the result line, and return `exit_code`.

- [ ] **Step 1: Failing tests:**
  - With only `suspect` and `info` findings, `exit_code` is 0. With one `stale` finding, it is 1.
  - `build_report` with `previous=None` contains `"first report"`. With `previous="unreadable"`, it contains `"previous report unreadable"`.
  - With a previous report holding the finding `X` and a current report holding `Y`, the output shows `Y` as new and `X` as resolved.
  - Findings are ordered `start`, `test`, `replay`, `stale`, `suspect`.
  - `main(["--skip-tests", "--journal-dir", str(synthetic_dir)])` uses the synthetic journal from Task 4's test, with `reports_dir` and the app dir monkeypatched to `tmp_path`. It writes both files, and the JSON `exit_code` matches the return value.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, then the full suite. Expected: only the 2 known failures.
- [ ] **Step 5: Commit** `feat: app status report and CLI`

---

### Task 9: Schedule, how-to, first real runs

**Files:** Create `tools/app_status/README.md` and `tools/app_status/register_monthly_task.ps1`.

- **`README.md`** covers four things, briefly:
  - **How to run**, with the exact commands: `.venv\Scripts\python.exe -m tools.app_status` and `... --full`.
  - **When to run it:**
    - quick before every merge to main;
    - quick after every Frontier game update;
    - full monthly (Task Scheduler).
  - **How to read the report.**
  - **How to update the files:** `live_confirmed.json` after an in-game confirmation, and `baselines.json` (raised only by hand).
- **`register_monthly_task.ps1`** works under PS 5.1 and 7.
  - It uses `Register-ScheduledTask` to create the task `EDChronicle App Status (monthly)`.
  - The task runs `<repo>\.venv\Scripts\python.exe -m tools.app_status --full` with working dir `<repo>`, monthly on day 1 at 10:00, only when the user is logged on.
  - The repo path is the script's own parent's parent's parent (`$PSScriptRoot\..\..`).
  - It does nothing unless run by Evan. The script is written, not executed.
  - Verify the cmdlet parameters against Microsoft docs. Unverified recall: `New-ScheduledTaskTrigger` has no `-Monthly` switch. If so, use a `-Weekly -WeeksInterval 4` trigger, or `schtasks /Create /SC MONTHLY /D 1`. Cite the source and the date checked in the task report.

- [ ] **Step 1:** Write both files.
- [ ] **Step 2:** Run `.venv/Scripts/python.exe -m tools.app_status` (quick) on the real setup. Record the result line, the duration and the attention list in the task report.
- [ ] **Step 3:** Run `--full` once. Record the same.
- [ ] **Step 4:** Commit `docs: app status how-to and monthly schedule script`.
