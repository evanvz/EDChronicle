# Colonisation System Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A system-type selector (Refinery, Service stop, Full build) in the Design window that plans a build fitted to each body's known slots, shows the projected outcome (stats, haul, Raven-style score), stores squad-entered slot counts on the hub, and corrects the economy-clash rule in both repos.

**Architecture:**
- **Hub (C:\Dev\EDDataHub):** a slot table, a write endpoint following the marks pattern, slot fields on `/api/colonisation-system`, and the three-economy rule in `service_stop`.
- **App (C:\Dev\EDChronicle):**
  - a facility data file;
  - a pure rule-based planner, `edc/core/colonisation_planner.py`, with no Qt;
  - client calls for hub slots and Raven Colonial slots;
  - the Design window wiring the selector, the slot grid and the plan output.
- The current template plan (`colonisation_design.plan_system`) stays as the fallback.

**Tech Stack:** Python 3.12, PyQt6, requests, psycopg 3 / PostgreSQL 18 (hub), pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-colonisation-system-planner-design.md`

## Global Constraints

- No new dependencies in either repo.
- No network call on the UI thread. QThread/worker objects stay referenced for the dialog's lifetime (EDChronicle CLAUDE.md).
- Raven Colonial is read-only: GET `{_BASE_URL}/api/v2/system/{name}` only, through `edc/core/raven_colonial.py`'s `_BASE_URL`. Nothing is sent to it.
- Hub writes from the app go only to our own hub (`PUT /api/colonisation-slots`), the same pattern as `/api/colonisation-mark`.
- Slot source order (trust): entered on the hub > Raven Colonial player-entered > estimate. The estimate is surface only (`ground_slots`); orbital without an entry is unknown (None).
- Every slot count carries its source: `"entered"`, `"raven"`, `"est"` or `None` (unknown).
- Unknown slots are never used by a plan; the plan warns instead.
- CP rules:
  - Tier 1 costs nothing and gives 1 T2 point.
  - A Tier 2 facility costs 1 T2 point and gives 1 T3 point. Large settlements give 2.
  - Coriolis and Asteroid Base: 3+ T2 cost, 1 T3 reward.
  - Tier 3 ports: 6+ T3 cost.
  - The primary port is free and doesn't count toward the ramp.
- Port cost ramp: for the n-th non-primary T2/T3 port (n counts T2 and T3 ports together):
  - T2 port cost = `3` for n ≤ 2, else `3 + (n-2)*2`;
  - T3 port cost = `6` for n ≤ 2, else `(n-1)*6`.
- Economy rule: a market is hurt only by a third or later economy. Both the app's `_clash` and the hub's `cannibalises` return `len(economies) > 2`.
- Raven-style score: the sum of each facility's `score` from the facility data. It's for comparison only, never for ranking candidates.
- Facility data: `settings/colonisation_facilities.json`.
  - Main source: the Raven Colonial site bundle (`https://ravencolonial.com/static/js/main.*.js`, the site-type table: `displayName2`, `subTypes`, `haul`, `tier`, `needs`, `gives`, `inf`, `score`, `effects`).
  - Cross-check: the ED wiki "System Colonisation" facility tables (MediaWiki API `action=parse&page=System_Colonisation&prop=wikitext`).
  - It has a top-level `"source"` and `"read"` date, plus a per-facility `"wiki_differs"` field.

## Review Focus

1. Body whose orbital count is unknown → no orbital facility is placed there, and the plan warns "orbital slots unknown: <body>". Test `test_unknown_orbital_never_used` (Task 6).
2. Raven Colonial body names that don't match the hub's names → those bodies are skipped, nothing raises. Test `test_raven_slots_skip_unmatched_names` (Task 5).
3. Primary body with 0 free orbital slots after the primary port → Service stop warns "no free orbital slot on the primary body for the Cartographics/Vista link" rather than placing the link elsewhere. Test `test_service_stop_no_link_slot_warns` (Task 6).
4. Slot entry that is negative, over 20, a bool or not an int → 400, nothing stored. Test `test_slots_put_rejects_bad_values` (Task 1).
5. System with no slot data at all (no entries, no Raven Colonial, no estimate) → the Design window shows the current template plan and a note "No slot counts yet: enter them to plan by type". Test `test_no_slots_falls_back_to_template` (Task 7).

---

### Task 1: Hub slot store and endpoint (EDDataHub)

**Files:**
- Create: `sql/023_colonisation_slots.sql`
- Modify: `eddatahub/colonisation.py` (new `set_slots`; `system()` adds slot fields per body)
- Modify: `eddatahub/web.py` (PUT path `/api/colonisation-slots`, next to `/api/colonisation-mark`)
- Modify: `deploy/web-role.sql` (grant)
- Test: `tests/test_colonisation.py`, `tests/test_web.py`

**Interfaces:**
- Produces:
  - `set_slots(conn, id64: int, body_id: int, orbital: int | None, surface: int | None, cmdr: str | None) -> str | None` (error text, or None when stored). Both counts None deletes the row.
  - `system()` bodies gain `"orbital_slots"` and `"surface_slots"` (int | None, entered values only).
  - `PUT /api/colonisation-slots` with JSON `{"id64", "body_id", "orbital", "surface", "cmdr"}` → 202 when stored, 400 with the error text.

- [ ] **Step 1: Write the failing tests**
  - `test_set_slots_round_trip`: `set_slots(conn, 1, 7, 2, 7, "Bob")` stores the row, and `system(conn, 1)["bodies"]` for body 7 has `orbital_slots == 2` and `surface_slots == 7`. Use the existing seed helpers so body 7 exists.
  - `test_set_slots_none_deletes`: after a set, `set_slots(conn, 1, 7, None, None, "Bob")` leaves no row, and the body shows `None` for both.
  - `test_slots_put_rejects_bad_values` (web): each of orbital = -1, 21, True, "3", 2.5 → 400, and no row is stored.
  - `test_slots_put_stores` (web): a valid body → 202, and a GET of the system shows the counts.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_colonisation.py tests/test_web.py -k slots -q` (PATH must include `C:\Dev\pgdev\pgsql\bin`; `PSYCOPG_IMPL=python`; `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/eddatahub_test`) → FAIL.
- [ ] **Step 3: Implement**
  - Migration: `SET LOCAL lock_timeout = '5s'; CREATE TABLE colonisation_slots (system_id64 bigint NOT NULL, body_id integer NOT NULL, orbital smallint, surface smallint, cmdr text, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (system_id64, body_id));` with no foreign key, the same as marks.
  - Validation in `set_slots`, mirroring `set_mark`'s style:
    - id64 and body_id are int and not bool;
    - each count is None or an int (not bool) from 0 to 20;
    - cmdr is None or text up to 200 characters.
  - `system()` LEFT JOINs the table.
  - web-role.sql: `GRANT INSERT, UPDATE, DELETE ON colonisation_slots TO "eddatahub-web";`
- [ ] **Step 4: Run** the focused tests, then the full hub suite → PASS.
- [ ] **Step 5: Commit** `feat: squad-entered colonisation slot counts`

### Task 2: Three-economy rule on the hub (EDDataHub)

**Files:**
- Modify: `eddatahub/service_stop.py` (`cannibalises`)
- Test: `tests/test_service_stop.py`

**Interfaces:**
- Produces: `cannibalises(economies: set[str]) -> bool`, which is `len(economies) > 2`. It's the twin of the app's `_clash`; keep the twin comment, updated.

- [ ] **Step 1: Failing test**
  - `test_two_economies_do_not_cannibalise`: `cannibalises({"Extraction", "Industrial"}) is False`, `cannibalises({"Refinery", "Industrial"}) is False`, `cannibalises({"Extraction", "Industrial", "HighTech"}) is True`.
  - Update `test_cannibalisation_rule` to the same rule.
- [ ] **Step 2: Run** `-k cannibal` → FAIL.
- [ ] **Step 3: Implement.** Change the comment source to "Frontier 2025-08-21/22: top two economies are not cannibalised".
- [ ] **Step 4: Run** the full hub suite → PASS. Fix any score assertions that relied on the old rule, recording each one in the commit message.
- [ ] **Step 5: Commit** `fix: only a third economy cannibalises a market`

### Task 3: Facility data file (EDChronicle)

**Files:**
- Create: `tools/build_colonisation_facilities.py` (one-off generator; kept so the data can be rebuilt)
- Create: `settings/colonisation_facilities.json`
- Create: `edc/core/colonisation_facilities.py`
- Test: `tests/test_colonisation_facilities.py`

**Interfaces:**
- Produces:
  - `load() -> dict[str, dict]`, keyed by facility key. The key is snake_case of Raven Colonial's `displayName2`: `"dodec_starport"`, `"refinery_hub"`, `"comms_installation"`, … Use Raven Colonial's exact display names, lower-cased, with each run of non-alphanumerics replaced by one `_` and the ends stripped (`"Mining Settlement: Large"` → `"mining_settlement_large"`, `"Mining/Industrial Installation"` → `"mining_industrial_installation"`). Make `"Communication Installation"` → `"comms_installation"` the one explicit alias.
  - Each record: `{"name", "rc_types": [str], "tier": int, "location": "orbital"|"surface", "economy": str|None, "requires": [str] (facility keys; [] for "First station"), "cp_cost": {"t2": int, "t3": int}, "cp_reward": {"t2": int, "t3": int}, "port": bool, "haul": int, "score": int, "effects": {"pop","mpop","sec","wealth","tech","sol","dev": int}, "wiki_differs": {field: [rc_value, wiki_value]}}`.
  - `"port"` is True for Coriolis, Asteroid, Orbis, Ocellus, Dodec and the Tier 3 Planetary Port; it marks the ones subject to the ramp.
  - `by_rc_type(build_type: str) -> dict | None`.

- [ ] **Step 1: Generate the file with the tool**
  - The tool reads the Raven Colonial bundle (find `main.*.js` from `https://ravencolonial.com/` index.html) and the wiki wikitext. It writes the JSON with `"source"`, `"read": "<today>"` and the records.
  - CP comes from Raven Colonial's `needs`/`gives`: `needs {tier: 2, count: 3}` → `cp_cost.t2 = 3`.
  - Requires comes from the wiki's "Requires" column: "First station" → `[]`; "Small/Medium/Large Mining Settlement" → the three extraction settlement keys; "Relay station" → `["relay_installation"]`, and so on.
  - Run it once; commit the JSON. The tool isn't imported by the app.
- [ ] **Step 2: Failing tests** in `test_colonisation_facilities.py`:
  - `test_known_values`:
    - `load()["dodec_starport"]` has tier 3, cp_cost.t3 6, score 15, effects.sec -4, haul 236000.
    - `load()["coriolis_starport"]["cp_reward"]["t3"] == 1`.
    - `load()["industrial_hub"]["requires"]` contains `"mining_industrial_installation"`.
    - `load()["refinery_hub"]["location"] == "surface"`.
  - `test_every_rc_type_maps`: `by_rc_type("dual_truss")["name"] == "Coriolis Starport"`; `by_rc_type("silenus")` is the Refinery Hub; `by_rc_type("nope") is None`.
  - `test_ports_flagged`: exactly the six port facilities have `port` True.
- [ ] **Step 3: Implement** the loader: a cached `json.load` of `settings/colonisation_facilities.json`, found the way other `settings/*.json` loaders find theirs.
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit** `feat: colonisation facility data (Raven Colonial table, wiki cross-check)`

### Task 4: Three-economy rule in the app

**Files:**
- Modify: `edc/core/colonisation_design.py` (`_clash`, the weak-point text, and the twin comment)
- Test: `tests/test_colonisation_design.py`, `tests/test_colonisation_design_dialog.py`

**Interfaces:**
- Produces: `_clash(econ: set) -> bool`, which is `len(econ) > 2`.

- [ ] **Step 1: Update failing expectations**
  - `test_usable_but_weak_pick_lists_reasons` now expects `["1,686 ls out", "no landable moons"]`: Extraction + Industrial no longer clash, so `_in_s_like` must still have two weak points. It does: far plus no moons.
  - Add `test_two_economies_no_clash_warning`: plan on gas giant 3 (TUC) has no warning containing "clash".
  - Add `test_three_economies_warn`: body economies `["Extraction", "HighTech", "Industrial"]` → a warning containing "clash".
  - The dialog weak-banner test expects the new text.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_colonisation_design.py tests/test_colonisation_design_dialog.py -q` → FAIL.
- [ ] **Step 3: Implement.** Comment source: "Frontier 2025-08-21/22: top two economies not cannibalised; twin of EDDataHub service_stop.cannibalises".
- [ ] **Step 4: Run** → PASS; then the full suite.
- [ ] **Step 5: Commit** `fix: only a third economy clashes in the Design window`

### Task 5: Slot clients (EDChronicle)

**Files:**
- Modify: `edc/core/eddatahub_client.py`
- Modify: `edc/core/raven_colonial.py`
- Test: `tests/test_eddatahub_client.py` (or the existing client test file), `tests/test_raven_colonial.py`

**Interfaces:**
- Produces:
  - `put_colonisation_slots(base_url: str, id64: int, body_id: int, orbital: int | None, surface: int | None, cmdr: str | None) -> bool`. A twin of `put_colonisation_mark`: requests.put with JSON, `_TIMEOUT`, and False on any error.
  - `get_system_slots(system_name: str) -> dict[str, tuple[int | None, int | None]] | None`, keyed by **body name** as Raven Colonial gives it.
    - It reads the `slots` map `{body num: [orbital, surface]}` and maps num → name through `bodies[].num/name`.
    - `-1` → `None`, meaning none/not applicable.
    - None when the system is unknown (404) or the request fails.
    - Synchronous: call it from a worker.

- [ ] **Step 1: Failing tests** (monkeypatch `requests`):
  - `test_put_slots_sends_json` / `test_put_slots_false_on_error`.
  - `test_raven_slots_by_body_name`: payload `{"bodies": [{"num": 3, "name": "X 3"}], "slots": {"3": [1, 2]}}` → `{"X 3": (1, 2)}`.
  - `test_raven_slots_minus_one_is_none`: `[3, -1]` → `(3, None)`.
  - `test_raven_slots_skip_unmatched_names`: a slots entry for num 9 with no body 9 is skipped, with no exception.
  - `test_raven_slots_404_none`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Use the existing URL style and `timeout=_TIMEOUT`; send `User-Agent` from `edc.version.USER_AGENT` on the new calls.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: hub and Raven Colonial slot clients`

### Task 6: The planner (EDChronicle, pure)

**Files:**
- Create: `edc/core/colonisation_planner.py`
- Test: `tests/test_colonisation_planner.py`, with fixtures shaped from ICZ DR-M b7-1 and Col 359 Sector LC-T d4-17 (bodies, clusters, slot counts as in the spec's examples; hand-written dicts, not network)

**Interfaces:**
- Consumes: `colonisation_facilities.load()` (Task 3); the hub system dict from `fetch_colonisation_system`, whose bodies now include `orbital_slots` / `surface_slots` (Task 1); Raven Colonial slots (Task 5).
- Produces:
  - `TYPES = ("refinery", "service", "full")`, with display names `{"refinery": "Refinery", "service": "Service stop", "full": "Full build"}` as `TYPE_NAMES`.
  - `slot_table(system: dict, raven: dict | None) -> list[dict]`. One row per body in `system["bodies"]` order: `{"body_id", "name", "orbital", "surface", "orbital_source", "surface_source"}`.
    - Source per count, first hit wins: the body's entered value → `"entered"`; Raven Colonial by exact body name → `"raven"`; surface only, `ground_slots` when not None → `"est"`; else count None and source None.
  - `port_cost(tier: int, n: int) -> int` for the n-th non-primary T2/T3 port, using the Global Constraints formulas. `n` is 1-based.
  - `plan(system: dict, slots: list[dict], primary_body: str, group: bool, kind: str) -> dict`, returning `{"steps": [...], "warnings": [str], "outcome": {...}, "unused": {"orbital": int, "surface": int}, "unknown": [str]}`.
    - Step: `{"title": str, "facility": key, "body": name, "location": "orbital"|"surface", "t2": int, "t3": int, "note": str|None}`, where t2/t3 are the balances after the step.
    - `outcome`: `{"stats": {"pop","mpop","sec","wealth","tech","sol","dev": int}, "haul": int, "score": int}`, summed over the primary and all steps.
- Rules (the decisions the implementer can't make alone):
  - **Primary:** solo → `coriolis_starport`; group → `ocellus_starport` if the primary body has rings, else `orbis_starport`. It uses one orbital slot of the primary body; if that body's orbital count is known and 0, warn "primary body shows no orbital slot". It adds its `cp_reward` and costs nothing; it is not counted in `port_cost`.
  - **Placement:** a facility goes only onto a body with a known count of that location and at least one left. Unknown counts are listed in `unknown` and warned about as `"orbital slots unknown: <name>"` / `"surface slots unknown: <name>"`. A facility is placed only when its `requires` (any one of them) is already in the steps or built, and its `cp_cost` is affordable from the current balance.
  - **Ports:** each non-primary port uses `port_cost(tier, n)` instead of its listed `cp_cost`.
  - **`service`:**
    - a Tier 3 primary needs no steps (note "Tier 3 primary: all services from the start");
    - else place `comms_installation` on the primary body's orbital slot. If none is free, warn "no free orbital slot on the primary body for the Cartographics/Vista link" and don't place it elsewhere.
  - **`refinery`:**
    1. A no-economy Tier 1 orbital on the primary body if a slot is free (`comms_installation`), else anywhere, for the T2 point and the link.
    2. `refinery_hub` on the primary body's surface slot. If there's no free surface slot on the primary body, warn "no surface slot on the primary body: no Refinery Hub" and stop.
    3. `mining_settlement_large` on the primary body if a surface slot is left and the T2 balance is at least 1, else `mining_settlement_medium`.
  - **`full`:**
    - **Theme per cluster** (`cluster` field; the primary's cluster first): the most frequent economy among its bodies' `economies`, ignoring `"Colony"` and `"Terraforming"`. Ties go to the earliest in `("Refinery", "Industrial", "HighTech", "Extraction", "Agriculture", "Military", "Tourism")`. Theme → families:
      - Refinery: refinery_hub plus mining settlements;
      - Industrial: industrial settlements plus industrial_hub (needs mining_industrial_installation);
      - HighTech: bio/scientific settlements plus high_tech_hub;
      - Extraction: mining settlements plus extraction_hub;
      - Agriculture: agriculture settlements plus civilian_hub;
      - Military: military settlements plus military_hub;
      - Tourism: tourist settlements plus space_bar_installation.
    - **Pass 1:** one medium settlement of the theme on each body with a free surface slot (T1, +1 T2).
    - **Pass 2:** free orbital slots get no-economy Tier 1 installations (satellite, comms, relay), cycling, for T2 points. Keep one orbital slot free per body that could still take a Tier 3 port.
    - **Pass 3:** large settlements of the theme on the remaining surface slots while the T2 balance is at least 1.
    - **Pass 4:** Tier 3 ports (`dodec_starport` in orbit; `large_planetary_port` on a surface slot when no orbital slot is left), while the T3 balance covers `port_cost(3, n)`.
    - **Pass 5:** the cluster hub on any remaining surface slot, when its requirement is met.
    - **Pass 6:** if `outcome.stats.sec < 0`, place `security_installation` (needs `relay_installation`; place the relay first if a slot allows), or else `military_settlement_medium` on remaining slots until sec ≥ 0 or no slots are left; otherwise warn "security below 0 after the plan".
  - **Every plan:**
    - warn "tech level <n> below 35: Tier 1 port shipyard/outfitting need 35 (unverified that this sum is the game's tech level)" when the primary is Tier 1 and stats.tech < 35;
    - `unused` counts the known free slots left.
- [ ] **Step 1: Failing tests**:
  - `test_port_cost_ramp`: T2 `[3, 3, 5, 7, 9]` for n = 1..5; T3 `[6, 6, 12, 18, 24]`.
  - `test_slot_sources_order`: entered beats raven beats est for surface; orbital with no entry and no raven is None/None.
  - `test_unknown_orbital_never_used` (Review Focus 1).
  - `test_service_t3_primary_no_steps` / `test_service_t2_adds_comms_on_primary` / `test_service_stop_no_link_slot_warns` (Review Focus 3).
  - `test_refinery_hub_on_primary_surface` / `test_refinery_no_surface_warns`.
  - `test_full_build_dr_m_shape`: on the DR-M-shaped fixture (9 orbital, 14 surface known), the plan leaves `unused == {"orbital": 0, "surface": 0}`, the T2 and T3 balances never go below 0 in any step, every step's requirement precedes it, and at least one Tier 3 port is placed.
  - `test_primary_free_and_not_ramped`: the first non-primary T3 port in a plan costs 6 even with a T3 primary.
  - `test_outcome_sums`: Coriolis primary alone → outcome stats equal the Coriolis effects, score 8, haul 63001.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_colonisation_planner.py -q` → FAIL.
- [ ] **Step 3: Implement** `colonisation_planner.py`. Pure functions only; no Qt, no network.
- [ ] **Step 4: Run** → PASS; then the full suite.
- [ ] **Step 5: Commit** `feat: rule-based colonisation planner by system type`

### Task 7: Design window wiring (EDChronicle)

**Files:**
- Modify: `edc/ui/panels/colonisation_design_dialog.py`
- Test: `tests/test_colonisation_design_dialog.py`

**Interfaces:**
- Consumes: Task 5 clients and the Task 6 `slot_table`, `plan`, `TYPES` and `TYPE_NAMES`.
- Produces: UI only.

- [ ] **Step 1: Failing tests**, using the existing `_dialog(monkeypatch, system)` helper, with `get_system_slots` and `put_colonisation_slots` monkeypatched on the dialog module:
  - `test_type_selector_lists_types`: the combo has "Template" plus the three `TYPE_NAMES`, with "Template" selected by default.
  - `test_slot_grid_shows_sources`: one row per body, with the orbital/surface counts and source text ("entered", "Raven", "est.", "?").
  - `test_full_build_renders_plan_and_outcome`: pick `full` on a fixture with known slots → the steps table holds the plan steps, and an outcome label shows "score", "haul" and "sec".
  - `test_save_slots_puts_each_changed_body`: edit a cell, press Save → `put_colonisation_slots` called with that body's id and the counts, and cmdr from `parent()._panel._last_state.commander`, as `_save_mark` does.
  - `test_no_slots_falls_back_to_template` (Review Focus 5).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - Keep the existing template path unchanged when "Template" is selected.
  - Add the type combo next to Solo/Group, plus a slot grid `QTableWidget` with columns Body, Orbital, Surface, Source. The counts are editable; the source isn't.
  - Add "Save slots" and an outcome `QLabel`.
  - Raven Colonial slots load in a worker started after the hub system loads, kept as an attribute (CLAUDE.md QThread rule). The grid refreshes when they arrive.
  - Save runs in a worker too; it sends only the rows changed since load.
  - Use the app's tab and button styles already in this file.
- [ ] **Step 4: Run** the dialog tests, then the full suite. Then run the app copy against the live hub (not offscreen; see the earlier probe approach) for Tucanae Sector IN-S b4-0 and ICZ DR-M b7-1. Save `grab()` screenshots and look at them.
- [ ] **Step 5: Commit** `feat: Design window plans by system type with squad slot counts`

### After the tasks (Evan)

1. Hub: `sudo bash /opt/eddatahub/app/deploy/update.sh` (applies 023 and the grant), then a full colonisation import overnight to re-score with the new economy rule.
2. In game: for one candidate system, enter the slots from Architect View, pick each type, and compare the plan with what the game allows. The issue stays open until Evan confirms.
