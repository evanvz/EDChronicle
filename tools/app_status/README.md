# App status report

Read-only health check. Writes `reports/app_status_YYYY-MM-DD.md` + `.json` (git-ignored; a second run the same day overwrites).

## Run

```
.venv\Scripts\python.exe -m tools.app_status
.venv\Scripts\python.exe -m tools.app_status --full
```

Other flags: `--all-journals` (full only), `--skip-tests`, `--journal-dir PATH`.
`--full` adds coverage, code health, a 30-day replay and the importer comparison; it takes many minutes.

## When

- Quick: before every merge to main, and after every Frontier game update.
- Full: monthly. `register_monthly_task.ps1` creates the Task Scheduler entry (day 1, 10:00, only while logged on). Run it by hand once.

## How to read the report

- The `**Result: PASS|FAIL**` line is also the exit code: 1 if any must-fix finding exists, else 0.
- Severity, worst first: `start`, `test`, `replay`, `stale` are must-fix. `suspect` means review. `info` is a note.
- "Since last report" compares with the previous report: new and resolved findings. Numbers inside a finding are ignored when matching, so a changed count is neither new nor resolved.
- Suspects are not certainties. Code health and sampled misses can be false positives.
- Network outages show as `info` notes, not failures.

## Update the files

Only after deciding a finding is expected. Edit by hand.

- `baselines.json`: raise a number (e.g. `exobio_sampled_misses`) to accept the new count, or add a table name to `dedupe_allowed_tables`.
- `live_confirmed.json`: after an in-game confirmation, set the area's `date` (YYYY-MM-DD) and `note`.
