# Colonisation System Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search the whole inhabited bubble for claimable systems, ranked by the port types their bodies allow and the economies those ports would give, with distance to the squad's systems.

**Architecture:**
- **EDDataHub** streams Spansh's galaxy dump once in full, then weekly from the 7-day file. It keeps only unpopulated systems in its existing `region_systems` set and stores a per-system summary (port types, economies, score) and per-body rows. Scores are precomputed.
- **Two JSON endpoints** serve the search and one system's bodies.
- **EDChronicle** adds a "Find Systems…" window to the Colonisation tab. It calls the hub through `edc/core/eddatahub_client.py`.

**Tech Stack:**
- Hub: Python 3, psycopg 3, Postgres, systemd timers.
- App: PyQt6 and `requests`.

**Spec:** `docs/superpowers/specs/2026-10-29-colonisation-system-finder-design.md`

## Global Constraints

- **Two repos.** Hub tasks run in `C:\Dev\EDDataHub` and app tasks in `C:\Dev\EDChronicle`. Each commit goes to its own repo. No push until Evan says so.
- **Hub tests** run against the local test Postgres. If it's down, start it with `pg_ctl start -D C:\Dev\pgdev\data -l C:\Dev\pgdev\server.log -o "-p 55432" -w` (PATH `C:\Dev\pgdev\pgsql\bin`), then run:
  `PSYCOPG_IMPL=python TEST_DATABASE_URL=postgresql://postgres@localhost:55432/eddatahub_test .venv/Scripts/python.exe -m pytest -q`
- **App tests:** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
- **Search speed:** a search must answer in about 1 s, so it reads only `colonisation_systems`, never body rows.
- **Unknown is not "no".** A port type or economy is only claimed when the body data shows it. A missing signal stays unknown.
- **Read-only use of third parties.** Nothing is pushed anywhere.
- **Spansh dump format,** sampled 2026-10-29:
  - The file is a JSON array with one system per line, ending in `,`. The first line is `[` and the last is `]`.
  - System keys: `id64, name, coords{x,y,z}, population, bodies[], bodyCount, date, stations[]`.
  - Body keys used here: `bodyId, name, type ('Star'|'Planet'|'Barycentre'), subType, isLandable, rings[], belts[], signals{signals{...}}, distanceToArrival, mainStar`.
  - Signal keys: `$SAA_SignalType_Biological;`, `$SAA_SignalType_Geological;`.
- **Dump URLs:**
  - `https://downloads.spansh.co.uk/galaxy.json.gz` (118 GB)
  - `https://downloads.spansh.co.uk/galaxy_7days.json.gz` (3.2 GB)
- **Rules source:** gaborauth/ed-colonisation-planner, `src/domain/economyOverrides.ts`, `computeBodyEconomyOverrides`. That repo cites Frontier's Update 3 patch notes of 2025-04-27. Checked 2026-10-29.
- **Hub limits:**
  - radius cap 200 ly;
  - `limit` default 100, maximum 500;
  - `near` at most 200 id64s;
  - **Only claimable systems are stored:** `to_populated_ly <= 15`. This is Evan's option B (2026-10-29). Region 1,566,939 systems × 250 B ≈ 390 MB was over the gate, while the claimable subset is about 130 MB (an estimate). There's a monthly full re-read to catch systems that become claimable.

## Review Focus

1. **A malformed or truncated dump line** (the stream cuts off mid-line) is skipped and counted, and the import carries on. Pinned in Task 3.
2. **A system with no bodies or only barycentres** is stored with an empty port-type list, a score of 0 and `body_count = 0`. It is shown as "unknown", not dropped. Pinned in Tasks 2 and 3.
3. **A system that became populated** in the weekly file is deleted from `colonisation_systems`. Pinned in Task 3.
4. **Bad endpoint input** (radius ≤ 0 or non-numeric, too many `near` ids) gives a 400, not a 500. A radius over 200 is clamped. Pinned in Task 4.
5. **The hub is unreachable or slow** in the app: the window shows "EDDataHub not reachable", the UI never blocks, and the Search button re-enables. Pinned in Task 7.

---

### Task 1: Measure first (stop gate, no code kept)

**Files:** none committed. Use a scratch script in the session scratchpad.

- [ ] **Step 1: Ask Evan to run on the server and paste the output:**
  `sudo -u eddatahub psql eddatahub -c "SELECT count(*) FROM region_systems;"`
- [ ] **Step 2: Estimate bodies per system.**
  - Stream `galaxy_7days.json.gz` locally for its first 50,000 systems with `population == 0`. Use `curl … | python` and keep nothing on disk.
  - Report the mean number of non-barycentre bodies.
- [ ] **Step 3: Compute the estimates.**
  - `systems_bytes ≈ region_count × 250`
  - `bodies_bytes ≈ region_count × mean_bodies × 150`
- [ ] **Step 4: Apply the gate.**
  - If `systems_bytes ≤ 300 MB`, continue. The search table only needs to fit in RAM; body rows are read one system at a time.
  - Otherwise stop and report to Evan with the numbers.
- [ ] **Step 5: Record the numbers** in the ledger and in memory `project-eddatahub-system-dump`.

### Task 2: Colonisation rules: body to port types and economies (hub)

**Files:**
- Create: `C:\Dev\EDDataHub\eddatahub\colonisation_rules.py`
- Create: `C:\Dev\EDDataHub\eddatahub\data\colonisation_rules.json`
- Test: `C:\Dev\EDDataHub\tests\test_colonisation_rules.py`

**Interfaces:**
- Produces:
  - `PORT_TYPES = ("Orbital", "Asteroid", "Surface")`
  - `body_ports(body: dict) -> list[str]`
  - `body_economies(body: dict) -> list[str]`
  - `summarise(system: dict) -> dict` with keys `port_types: list[str], economies: list[str], score: int, body_count: int, main_star: str | None`

**Rules file content.** One JSON object, with a `source` string naming the repo, file, function and "checked 2026-10-29":
- `star`:
  - `{"Black Hole": [...], "Neutron Star": [...], "White Dwarf": [...]}`: HighTech and Tourism. Match on subType containing "Black Hole", "Neutron" or "White Dwarf".
  - Any other star: Military.
- `planet` (matched on Spansh `subType`):
  - Earth-like world: Agriculture, HighTech, Military, Tourism.
  - Water world: Agriculture, Tourism.
  - Ammonia world: HighTech, Tourism.
  - Any `subType` containing "gas giant": HighTech, Industrial.
  - High metal content world and Metal-rich body: Extraction.
  - Rocky Ice world: Industrial, Refinery.
  - Rocky body: Refinery.
  - Icy body: Industrial.
- `rings`: Extraction (a body with `rings` or `belts`).
- `signals`:
  - `$SAA_SignalType_Biological;`: Agriculture, Terraforming.
  - `$SAA_SignalType_Geological;`: Extraction, Industrial.
  - Only for landable bodies, and only when the key is present. Absent means unknown, so nothing is added.

**Ports.**
- Orbital: every Star or Planet body.
- Asteroid: a body with `rings` or `belts`.
- Surface: `isLandable` is true.
- Barycentres give nothing.

**Score** = `10 × len(port_types) + len(economies)`. This rewards port variety first and economy variety second, per the spec. Show the formula in the app tooltip (Task 7).

- [ ] **Step 1: Write the failing tests:**

```python
def test_landable_ringed_icy_body():
    b = {"type": "Planet", "subType": "Icy body", "isLandable": True, "rings": [{"type": "Icy"}]}
    assert body_ports(b) == ["Orbital", "Asteroid", "Surface"]
    assert body_economies(b) == ["Extraction", "Industrial"]

def test_signals_only_count_when_present_and_landable():
    bio = {"signals": {"signals": {"$SAA_SignalType_Biological;": 2}}}
    assert "Agriculture" in body_economies({"type": "Planet", "subType": "Rocky body", "isLandable": True, **bio})
    assert body_economies({"type": "Planet", "subType": "Rocky body", "isLandable": False, **bio}) == ["Refinery"]

def test_star_types():
    assert body_economies({"type": "Star", "subType": "Neutron Star"}) == ["HighTech", "Tourism"]
    assert body_economies({"type": "Star", "subType": "K (Yellow-Orange) Star"}) == ["Military"]

def test_summary_and_empty_system():
    s = summarise({"bodies": [{"type": "Star", "subType": "M (Red dwarf) Star", "mainStar": True},
                              {"type": "Planet", "subType": "Water world", "isLandable": False}]})
    assert s == {"port_types": ["Orbital"], "economies": ["Agriculture", "Military", "Tourism"],
                 "score": 13, "body_count": 2, "main_star": "M (Red dwarf) Star"}
    assert summarise({"bodies": [{"type": "Barycentre"}]}) == {
        "port_types": [], "economies": [], "score": 0, "body_count": 0, "main_star": None}
```

  Lists are sorted alphabetically, except `port_types`, which follows `PORT_TYPES` order.
- [ ] **Step 2: Run** `pytest tests/test_colonisation_rules.py -q`. Expect FAIL: an import error.
- [ ] **Step 3: Implement.** Load the JSON once at import time. The functions are pure.
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: colonisation port-type and economy rules`.

### Task 3: Tables and import (hub)

**Files:**
- Create: `C:\Dev\EDDataHub\sql\018_colonisation.sql`
- Create: `C:\Dev\EDDataHub\eddatahub\colonisation.py`
- Modify: `C:\Dev\EDDataHub\eddatahub\__main__.py`, adding the `colonisation-import [--full]` subcommand and the docstring line.
- Create: `C:\Dev\EDDataHub\deploy\eddatahub-colonisation.service` and `.timer`. Copy the `eddatahub-region` units. The timer is `OnCalendar=Mon *-*-* 05:00:00 UTC`, `Persistent=true`. `ExecStart` runs `-m eddatahub colonisation-import`.
- Test: `C:\Dev\EDDataHub\tests\test_colonisation.py`

**Migration 018:**
- `colonisation_systems`:
  - `system_id64 bigint PK, name text, x, y, z double precision`;
  - `to_populated_ly real`;
  - `main_star text, body_count int`;
  - `port_types text[], economies text[], score int`;
  - `dump_date timestamptz, imported_at timestamptz DEFAULT now()`.
  - Indexes on `(x, z)` and `(score DESC)`.
- `colonisation_bodies`:
  - `system_id64 bigint, body_id int, name text, sub_type text, landable bool, distance_ls real, port_types text[], economies text[]`;
  - PK `(system_id64, body_id)`;
  - `ON DELETE CASCADE` FK to `colonisation_systems`.
- `colonisation_runs`: `(run_at timestamptz, kind text CHECK IN ('full','week'), lines bigint, kept bigint, removed bigint, bad bigint)`.

**Interfaces:**
- Consumes: `colonisation_rules.summarise`, `body_ports` and `body_economies` (Task 2).
- Produces:
  - `parse_line(line: str) -> dict | None`. It strips the trailing `,`; `[`, `]` and bad JSON give None.
  - `load(conn, lines: Iterable[str], kind: str) -> dict` returning `{"lines", "kept", "removed", "bad"}`.
  - `run(conn, full: bool = False) -> dict`, which picks the URL and streams it with `urllib` and `gzip`, like `region.py`. It does a full read when `full`, or when the last `'full'` row in `colonisation_runs` is over 30 days old, or when there isn't one (`FULL_EVERY = timedelta(days=30)`, as in `region.py`).

**`load` rules:**
- Keep a system when its `id64` is in `region_systems` (load the id set once), `population` is 0 or missing, **and** `to_populated_ly <= 15`. A stored system that is now further than 15 ly (its populated neighbour emptied) is deleted and counted as `removed`.
- If a system's `id64` is in the set and `population > 0`, delete its row and count it as `removed`.
- `to_populated_ly` is the distance to the nearest populated system. Get those from the `POPULATED` query in `region.py`; reuse it, don't copy it. Use a 15 ly grid bucket lookup, not an all-pairs scan. *ponytail note: a cell grid, which is enough for about 30k populated systems.*
- Upsert in chunks of 5,000 systems with one transaction per chunk. Replace a system's bodies on each upsert.

- [ ] **Step 1: Write the failing tests** (test DB, with a few `region_systems` rows and one populated `current_facts` system):
  - `test_parse_line_handles_brackets_commas_and_garbage`: `parse_line("[")`, `parse_line("]")` and `parse_line('{"id64": 1,')` are all `None`. A valid line with a trailing comma parses.
  - `test_load_keeps_only_unpopulated_region_systems`: three lines are in the region with population 0, 5 and 0, plus one id outside the region. The result is `kept == 2`, and rows exist only for the two.
  - `test_populated_later_is_removed`: load once with population 0, then again with population 10. The row is gone, `removed == 1`, and its bodies are deleted too.
  - `test_truncated_line_counts_bad_and_continues`: a line cut mid-JSON before a good line gives `bad == 1, kept == 1`.
  - `test_to_populated_distance`: a system 10 ly from the populated system gets `to_populated_ly == pytest.approx(10, abs=0.01)`. A system 20 ly away isn't stored.
  - `test_run_goes_full_after_30_days`: with no `'full'` run, or one 31 days old, `run` picks the full URL. With one 2 days old, it picks the 7-day URL. Monkeypatch the stream.
  - `test_empty_system_stored_with_zero_score`: a system with only a barycentre is stored with `score == 0, body_count == 0`.
- [ ] **Step 2: Run** `pytest tests/test_colonisation.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** the migration, `colonisation.py`, the CLI and the units.
- [ ] **Step 4: Run** the test file, then the full hub suite. Expect PASS.
- [ ] **Step 5: Commit** `feat: colonisation candidates imported from Spansh's dump`.

### Task 4: Search endpoints (hub)

**Files:**
- Modify: `C:\Dev\EDDataHub\eddatahub\colonisation.py`, adding `search` and `system`.
- Modify: `C:\Dev\EDDataHub\eddatahub\web.py`, adding two routes in `do_GET`, in the pattern of `/api/system-powerplay`.
- Test: `C:\Dev\EDDataHub\tests\test_colonisation.py`, `tests/test_web.py`

**Interfaces:**
- `search(conn, x, y, z, radius, port_types: list[str], economies: list[str], near: list[int], near_max: float | None, limit: int = 100) -> list[dict]`.
  - Row keys: `id64, name, x, y, z, distance_ly, to_squad_ly (None when no near), to_populated_ly, port_types, economies, score, body_count, dump_date`.
  - Sort: score descending, then distance ascending.
  - Filters:
    - a bounding box plus the true distance;
    - `port_types @> %s` and `economies @> %s`;
  - `near` positions come from `region_systems`. `to_squad_ly` is the minimum distance to them, computed in SQL or Python over the at most `limit × 3` rows already returned (*my call*). When `near_max` is set, rows beyond it are dropped before the limit.
- `system(conn, id64: int) -> dict | None` returns the system row plus `bodies: [{name, sub_type, landable, distance_ls, port_types, economies}]`, sorted by distance.
- Routes:
  - `GET /api/colonisation-search?x&y&z&radius&port_type=…&economy=…&near=id,id&near_max&limit`
  - `GET /api/colonisation-system?id64=`
- Errors:
  - 400 for a bad number, `radius <= 0`, more than 200 `near` ids, or a bad `id64`;
  - 404 for an unknown system;
  - 503 when the DB is unreachable.
  - A radius over 200 is clamped to 200, and `limit` is clamped to 1–500.

- [ ] **Step 1: Write the failing tests:**
  - `test_search_ranks_by_score_then_distance`
  - `test_search_filters_port_type_and_economy`
  - `test_search_near_squad_distance_and_limit`
  - `test_system_returns_bodies_sorted`
  - In `test_web.py`:
    - `test_colonisation_search_bad_radius_is_400`: `radius=abc` and `radius=0` give 400;
    - `test_colonisation_search_too_many_near_is_400`: 201 ids give 400;
    - `test_colonisation_system_unknown_is_404`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full hub suite. Expect PASS.
- [ ] **Step 5: Timing check.** Seed 300,000 synthetic systems in the test DB, then time one `search` call with a 200 ly radius. Expect under 1 s. Record the time in the ledger.
- [ ] **Step 6: Commit** `feat: colonisation search endpoints`.

### Task 5: First import on the server (Evan runs it)

- [ ] **Step 1:** Push the hub (ask Evan first). Evan runs `sudo -v`, then `sudo bash /opt/eddatahub/app/deploy/update.sh`. Migration 018 is applied.
- [ ] **Step 2:** Evan starts the full import in the background:
  ```
  sudo -u eddatahub bash -c 'cd /opt/eddatahub/app && set -a && . /etc/eddatahub.env && set +a && nohup .venv/bin/python -m eddatahub colonisation-import --full > /tmp/colonisation-full.log 2>&1 &'
  ```
  It reads 118 GB, so expect hours.
- [ ] **Step 3:** When it ends, Evan pastes `tail -5 /tmp/colonisation-full.log` and the output of:
  `curl -s -o /dev/null -w "%{time_total}\n" "http://localhost:8080/api/colonisation-search?x=0&y=0&z=0&radius=200"`
  Expect the time to be at most 1 s.

### Task 6: Hub client functions (app)

**Files:**
- Modify: `C:\Dev\EDChronicle\edc\core\eddatahub_client.py`
- Test: `C:\Dev\EDChronicle\tests\test_eddatahub_colonisation.py` (new; mock `requests.get` the way `tests/test_eddatahub_pp_week.py` does)

**Interfaces:**
- `fetch_colonisation_search(base_url: str, x: float, y: float, z: float, radius: float, port_types: List[str], economies: List[str], near: List[int], near_max: Optional[float], limit: int = 100) -> Optional[List[dict]]`
- `fetch_colonisation_system(base_url: str, id64: int) -> Optional[dict]`
- Both use `_TIMEOUT` and `USER_AGENT`, and return `None` on any request or JSON error. Follow `fetch_system_powerplay`.

- [ ] **Step 1: Failing tests:**
  - query parameters are built correctly (repeated `port_type`, comma-joined `near`);
  - a timeout gives `None`;
  - a non-list answer gives `None`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expect PASS.
- [ ] **Step 5: Commit** `feat: hub client for colonisation search`.

### Task 7: "Find Systems…" window (app)

**Files:**
- Create: `C:\Dev\EDChronicle\edc\ui\panels\colonisation_finder_dialog.py`
- Modify: `C:\Dev\EDChronicle\edc\ui\panels\colonisation_panel.py`, adding the button and dialog ownership, in the pattern of `_RavenColonialDialog`.
- Test: `C:\Dev\EDChronicle\tests\test_colonisation_finder_dialog.py`

**Interfaces:**
- Consumes: Task 6's functions. Also:
  - `edc.core.colonisation_eligibility._spansh_claimed(system_name) -> Optional[bool]`;
  - `Repository.get_player_faction_overview()` for the squad's `system_address` list;
  - `edc.ui.panels.market_panel._NumericTableWidgetItem`.
- Produces: `ColonisationFinderDialog(panel, hub_url: str)`, a non-modal QDialog.

**Layout:**
- **Search row:**
  - centre system: a QLineEdit, defaulting to the current system;
  - radius: a QSpinBox, 10–200, default 100;
  - port type and economy: QComboBox, with "Any" first;
  - "Near squad" checkbox, plus a ly spinbox defaulting to 30;
  - Search button.
- **Results table:** a filter-by-name box, as in the Combat System Status table.
  - Columns: `System | Dist (ly) | To squad (ly) | Score | Port types | Economies | Bodies | Data age`.
  - Numeric columns use `_NumericTableWidgetItem`. Sorting is on, and is turned off while the table fills.
  - A Score header tooltip: "Score = 10 × port types + economies (rules: Update 3 body economies)".
  - A row with `body_count == 0` shows "unknown" under Port types.
- **Selecting a row:**
  - fills a lower bodies table (`Body | Type | Landable | Dist (ls) | Port types | Economies`) from `fetch_colonisation_system`;
  - shows a "Spansh: claimed / free / unknown" label from `_spansh_claimed`.
- **Clicking the System cell** copies the name.
- **Centre coordinates:** use the current state's x/y/z when the centre is the current system. Otherwise look the name up with `Repository.get_system_coords_for_names([name])`; if that's unknown, show "Unknown system — jump there or pick a known one".
- **Threading:** every hub and Spansh call runs on a worker `QObject` with a `QThread` kept as an attribute (never a local). Connect `finished → quit` with `Qt.ConnectionType.DirectConnection` (`tests/test_thread_quit_direct.py` guards this).
- **The button** is disabled with the tooltip "Needs EDDataHub (Settings → EDDataHub URL)" when `cfg.eddatahub_url` is empty.

- [ ] **Step 1: Failing tests** (a QApplication fixture with a fake panel, a fake repo and monkeypatched client functions):
  - `test_results_render_sorted_and_unknown_ports`
  - `test_filter_box_hides_other_systems`
  - `test_hub_unreachable_shows_message_and_reenables_search`: the client returns `None`, the status says "EDDataHub not reachable", and the Search button is enabled.
  - `test_near_squad_sends_squad_ids`
  - `test_button_disabled_without_hub_url`
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full app suite. Expect PASS. Confirm `tests/test_thread_quit_direct.py` passes.
- [ ] **Step 5: Live check.** Run the app against the live hub, open Colonisation → "Find Systems…", search 100 ly from the current system, click a row, and take a screenshot.
- [ ] **Step 6: Commit** `feat: Colonisation Find Systems window (EDDataHub search)`.
