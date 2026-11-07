# App Status Report — Design

Date: 2026-11-07. Status: approved by Evan 2026-11-07.

## Intent and why

EDChronicle has grown fast: about 54,000 lines in `edc/` plus 5,000 in `persistence/`, 28 UI panels, and many features added in quick succession. Most of them were never retested after later changes. Evan knows of no current bug, but he can't say there are none. He wants a reusable **app status check** that produces an **App Status Report**. The report should either give him back the confidence that the app is in good order and every function does what it should, or show him where it isn't.

The check should be repeatable: run it now, run it again after big changes, and compare.

## Goals

1. One command produces one dated report.
2. The report covers every feature area. Each area gets five columns:
   - **Tests**: pass, fail or none. The automated pytest result for the area's test files.
   - **Replay**: OK or problem. Evan's real journals are run through the app's event engine against a *copy* of his database. The column records any exceptions, plus area-specific sanity results (below).
   - **Data fresh**: the newest timestamp in each table the area writes to in Evan's DB. This catches a feed or handler that silently stopped.
   - **Code health**: counts of unused code, duplicated logic, and lines the tests never execute.
   - **Last live-confirmed**: the date Evan last saw the area working in-game, or "never".
3. The report ends with an **attention list**, worst first.
4. The app must start: the main window is built headless (`QT_QPA_PLATFORM=offscreen`), and every panel refreshes once without an exception.
5. Errors in the recent app logs (`logs/edc_*.log`) are counted per module and fed into the matching area.

## Feature areas (rows)

Overview/HUD; BGS & factions (incl. ticks, conflicts, expansion forecast); Powerplay; Colonisation & system planner; Exploration & exobiology; Trade, markets & routes; Mining; Missions; Megaships; Engineering & materials; Combat scanners (bounty, fines, notoriety, combat bonds); Squadron; EDDN sending; EDDataHub link; Raven Colonial & EDSM push; Voice; Other.

Every test file and every `edc/` module must map to exactly one area, with "Other" as the catch-all. The mapping is one hand-maintained file in the repo. The report lists anything that is unmapped, so the mapping can't silently rot.

## Replay sanity checks (starting set)

Every area: zero exceptions during replay. Extra checks, which the builder extends where an area has an obvious one:
- Exploration & exobiology: every body with bio signals gets a prediction, and sampled species are inside the prediction. Baseline from 2026-11-07: 3 misses in 899.
- BGS: FSDJump/Location events that carry Factions produce faction snapshots.
- Trade: Market events produce market rows.
- Missions: MissionCompleted produces completion rows, with no duplicates. A duplicate-completion bug happened before; see `data/backup_duplicate_mission_completions_2026-10-23.json`.
- Colonisation: ColonisationConstructionDepot events produce depot progress.

## Known duplicate-logic suspect to report on

`edc/core/journal_importer.py` (bulk import) and the live handlers under `edc/engine/handlers/` both process Scan, Docked, CodexEntry, ScanOrganic, SAASignalsFound and others. A divergence between them caused the 2026-11-07 exobiology "0 of 168 predicted" bug. The report lists every journal event handled by both paths, so each pair can be reviewed.

## Constraints

- **Never touch live data.** Work on a copy of `data/edhelper.db`, made with SQLite's backup API so a running app's WAL is respected, inside an auto-deleting temp directory. Skip `network_cache.db` (4.4 GB). Don't copy it unless an area truly needs it.
- **Nothing leaves the machine during the check.** Replay must not publish to EDDN, push to EDSM or Raven Colonial, call EDDataHub, or speak through voice. Outbound senders are disabled or stubbed for the run. The report states that they were.
- **Report only.** The check never changes code, config or data. Fixes are separate work that Evan approves.
- Dev-only tools (coverage, unused-code and duplicate finders) go in a separate dev requirements file. They are not added to `requirements.txt` and not shipped to users.
- Runs on Windows with the project `.venv`, on both of Evan's laptops. Paths come from the existing config (`journal_dir`) and the data folder, not hard-coded.
- Python only, simple scripts; follow the repo's existing style.

## Non-goals

- The deep, read-every-line subsystem reviews. Those are follow-up work, done area by area and *driven by* this report's attention list.
- Fixing anything found.
- A UI tab in the app. The report is a file.
- A cloud-run schedule. The check needs Evan's local journals and DB.

## Anti-goals (failure even if it "works")

- A report that is all green because it checks nothing meaningful, for example tests that pass but replay checks that assert nothing.
- Any write to the real DB, settings or journals, or any outbound network traffic.
- Unused-code findings presented as certainties. Qt signal slots, handler registries and journal-event dispatch make code look unused when it isn't. Mark them as **suspects**.
- A check so slow it never gets run.

## Decided by Evan

- An App Status Report, shaped as above: rows per area, the five columns, and an attention list (approved 2026-11-07, "go ahead").

## My calls (Evan to check)

- **Report format and place:** Markdown, `reports/app_status_YYYY-MM-DD.md`. The folder is git-ignored and kept so reports can be compared over time. Each report states the app version (`edc/version.py`) and the git commit.
- **"Last live-confirmed" source:** a small repo file listing area, date and note. It is updated whenever Evan confirms something in-game. Claude's memory notes are not readable by a script.
- **Replay window:** see the two modes below.
- **Schedule:**
  - before merging any feature branch to main;
  - after each Frontier game update;
  - monthly.

  The monthly run uses a Windows Task Scheduler job that runs the same command. A reminder to read the report is enough; the run itself needs no Claude session.
- **Comparison:** the report shows what changed since the previous report, for example new failures and new suspects.

- **Replay starts from an empty DB.** Replaying into a copy that already holds those events would only test dedupe, and checks could pass trivially. So the replay works like this:
  1. Run the journals through the live `event_engine` path into a fresh DB with the schema created. This tests first-time processing, and the sanity checks run on it.
  2. Replay the same journals a second time into that same DB. No row counts may change. This is the dedupe/idempotency check.
  3. Run `journal_importer.py` over the same journals into another fresh DB, then compare the tables both paths write. Every difference is listed. This is how the duplicate-logic suspect gets tested, not just named.
  4. Use the copy of the real DB only for the **Data fresh** column.
- **Stubbing for replay:** Qt is allowed headless, and threads, timers and network senders may be stubbed. The event order must be the journals' own order.
- **Sanity baselines:** stored in a repo baseline file next to the area mapping. Each check has a number, for example exobiology misses = 3. Worse than the baseline is a failure. Better is reported, and the baseline is only raised by hand.
- **Stale data:** measured against the newest journal event, not today, so a week without playing doesn't turn everything red. Feeds that don't depend on play (EDDataHub, tick sources) are measured against now. Each area has its own threshold in the mapping file, because some feeds are naturally sparse.
- **Two modes:**
  - **quick** (default; before merges and after game updates): tests without coverage, 7-day replay, app-start check, log scan, freshness. Target is under about 5 minutes.
  - **full** (monthly): adds coverage, the unused-code and duplicate scans, the 30-day replay, and the importer comparison. An extra `--all-journals` option replays everything.
- **Exit code:** non-zero when the attention list has a failure (won't start, test failure, replay exception or check worse than baseline, stale beyond threshold). Code-health suspects alone don't fail it. It always writes the report first.
- **Machine-readable copy:** a JSON file is written next to each markdown report. The previous-report comparison reads the JSON.

## Left to the builder

- Tool choice for unused code, duplicates and coverage, as long as they are dev-only and run offline.
- How outbound senders are stubbed during replay.
- The exact freshness tables per area, and any extra sanity checks.
- How "worst first" is ranked. A sensible order is: app won't start, test failure, replay exception, stale data, code-health suspects.
