# Colonisation Service Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score claimable systems as player "service stops" in the hub and add a System Design window in EDChronicle that plans the build around the player-picked primary-slot body, or marks the system a poor pick.

**Architecture:** EDDataHub owns body facts, ground-slot estimates, clusters and the service-stop score (computed at import, stored in new columns, returned by the two existing colonisation routes). EDChronicle shows the score in Find Systems and builds the plan text and poor-pick verdict in a pure module from the hub's per-body fields; a new dialog renders it.

**Tech Stack:** Python 3, PostgreSQL 18 (psycopg), PyQt6, pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-colonisation-service-stop-design.md` (EDChronicle repo).

## Global Constraints

- Two repos: hub `C:\Dev\EDDataHub`, app `C:\Dev\EDChronicle`. Each task names its repo; commit in that repo only.
- Hub tests: `PATH=/c/Dev/pgdev/pgsql/bin:$PATH PSYCOPG_IMPL=python TEST_DATABASE_URL=postgresql://postgres@localhost:55432/eddatahub_test .venv/Scripts/python.exe -m pytest -q` (start Postgres with `pg_ctl start -D /c/Dev/pgdev/data -l /c/Dev/pgdev/server.log -o "-p 55432" -w` if `pg_ctl status` says it is not running). App tests: `.venv/Scripts/python.exe -m pytest -q`.
- No slot or cluster logic in the app; no plan logic in the hub.
- Every rule carries its source in a comment: Dubior = *CMDR Dubior's Advanced ED Colonization Guide* (ref. 2026-08-11); 101 = *Colonization 101* (PhoenixBlue0); DaftMav = Service Unlocks flowchart. Community-reported, not official.
- Ground slots (Dubior "Slot Count"): 0 if temperature ≥ 700 K or gravity ≥ 2.7 g; else radius < 1500 km → 1, < 3750 → 2, < 6000 → 3, ≥ 6000 → 4; +2 atmosphere, +1 terraformable, +1 high metal content (`subType` "High metal content world"), +1 geologicals; max 7. Only landable planets have ground slots; non-landable → 0. Missing radius, gravity or temperature on a landable body → `None` ("?").
- Cluster root: walk `parents` (list of single-key dicts, nearest first), skip `Null`/`Barycentre`; root is the nearest `Planet` ancestor, else the body itself if it is a Planet. Stars and belts are never roots (cluster `None`).
- Cannibalisation (Dubior "Mixed Economy Setups"): Agriculture/Extraction/Refinery/Tourism mix well; Industrial and High Tech clash with any other economy; Refinery+Industrial is the worst pair.
- Market before outfitting (Evan, 2026-10-30): the main port keeps its natural top two economies; High Tech builds go on a different cluster, or are left out with the note that outfitting stock stays at default.
- No data is sent to Raven Colonial or any third party. Spansh `/api/dump/<id64>` is only read, once, to build test fixtures.
- Ordering that must hold: Tucanae Sector PY-R b4-1 > ICZ KX-T b3-3 > CD-55 35 by `service_score`.
- Hub commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; same for the app.

## Review Focus

1. Systems with no bodies in the dump (36.7% of systems): the score must be 0 with reason "no body data", not NULL or a crash. Test in Task 2.
2. Rows imported before migration 020 (`service_score` NULL): the finder shows a blank cell and sorts them below scored rows; the search orders NULLs last. Tests in Tasks 3 and 4.
3. Landable body with missing radius/gravity/temperature: `ground_slots` is `None`, shown "?", counts 0. Test in Task 1.
4. Primary picked on a star, a belt cluster, or a body with no landable moon in its cluster: poor pick with a reason, no steps. Test in Task 5.
5. Hub not yet deployed (response lacks the new keys): the app must not raise; Design shows "Hub has no body details yet". Test in Tasks 4 and 6.

---

### Task 1 (hub): body facts, ground slots, clusters

**Files:**
- Create: `eddatahub/service_stop.py`
- Create: `tests/fixtures/colonisation/tucanae_py_r_b4_1.json`, `icz_kx_t_b3_3.json`, `cd_55_35.json`
- Test: `tests/test_service_stop.py`

**Interfaces:**
- Produces: `body_facts(b: dict) -> dict` with keys `parent_id: int|None, rings: bool, atmosphere: bool, terraformable: bool, geo: bool, bio: bool, tidally_locked: bool|None, radius_km: float|None, gravity_g: float|None, temperature_k: float|None, ground_slots: int|None`; `clusters(bodies: list[dict]) -> dict[int, int|None]` mapping each Spansh `bodyId` to its cluster root `bodyId`.

- [ ] **Step 1: Build fixtures.** For id64s 2870782273001 (Tucanae Sector PY-R b4-1), 7268560741817 (ICZ KX-T b3-3), 147933071723 (CD-55 35): `curl -s https://spansh.co.uk/api/dump/<id64>` and save the `system` object as the fixture file (pretty-printed). Read-only use; note the date fetched in a `_fetched` key.
- [ ] **Step 2: Write the failing tests**

```python
def _sys(name): return json.loads((FIX / name).read_text())

def test_ground_slots_follow_dubior():
    tuc = {b["name"]: b for b in _sys("tucanae_py_r_b4_1.json")["bodies"]}
    assert service_stop.body_facts(tuc["Tucanae Sector PY-R b4-1 3 a"])["ground_slots"] == 2   # 776 km → 1, +1 geo
    assert service_stop.body_facts(tuc["Tucanae Sector PY-R b4-1 3"])["ground_slots"] == 0     # gas giant, not landable
    hot = {"type": "Planet", "subType": "High metal content world", "isLandable": True, "radius": 7000,
           "gravity": 1.0, "surfaceTemperature": 800}
    assert service_stop.body_facts(hot)["ground_slots"] == 0
    rich = {**hot, "surfaceTemperature": 300, "atmosphereType": "Thin Carbon dioxide",
            "terraformingState": "Terraformable", "signals": {"signals": {"$SAA_SignalType_Geological;": 1}}}
    assert service_stop.body_facts(rich)["ground_slots"] == 7          # 4 +2 +1 +1 +1 = 9, capped

def test_missing_size_is_unknown_not_zero():
    assert service_stop.body_facts({"type": "Planet", "isLandable": True, "radius": 900})["ground_slots"] is None

def test_clusters_root_at_nearest_planet():
    s = _sys("tucanae_py_r_b4_1.json")
    c = service_stop.clusters(s["bodies"])
    ids = {b["name"].removeprefix(s["name"] + " "): b["bodyId"] for b in s["bodies"]}
    assert c[ids["3 a"]] == c[ids["3"]] == ids["3"]
    assert c[ids["1"]] == ids["1"]                 # planet orbiting the star: own cluster
    assert c[ids[""]] is None                      # the star (single-star system: name == system name)
```

- [ ] **Step 3: Run** the hub test command on `tests/test_service_stop.py`. Expected: FAIL, `service_stop` not found.
- [ ] **Step 4: Implement** `body_facts` and `clusters` in `eddatahub/service_stop.py`. Atmosphere = `atmosphereType` non-empty and not "No atmosphere"; terraformable = `terraformingState` in ("Terraformable", "Terraforming", "Terraformed"); geo/bio from `signals.signals` keys `$SAA_SignalType_Geological;` / `$SAA_SignalType_Biological;`; rings = `rings` or `belts` non-empty; reuse `region._num` for numeric checks.
- [ ] **Step 5: Run** tests. Expected: PASS.
- [ ] **Step 6: Commit** `feat: colonisation body facts, ground slots and clusters (Dubior rules)`.

### Task 2 (hub): service-stop score and reason

**Files:**
- Modify: `eddatahub/service_stop.py`
- Test: `tests/test_service_stop.py`

**Interfaces:**
- Consumes: Task 1 `body_facts`, `clusters`; `colonisation_rules.body_economies(b) -> list[str]`.
- Produces: `cannibalises(economies: set[str]) -> bool`; `service_stop(system: dict) -> tuple[int, str]` taking one Spansh system dict, returning `(score, reason)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_three_systems_rank_tucanae_icz_cd55():
    t, i, c = (service_stop.service_stop(_sys(n))[0] for n in
               ("tucanae_py_r_b4_1.json", "icz_kx_t_b3_3.json", "cd_55_35.json"))
    assert t > i > c

def test_reason_names_best_cluster():
    score, reason = service_stop.service_stop(_sys("tucanae_py_r_b4_1.json"))
    assert reason.startswith("Gas giant 3 at 898 ls:") and "landable moons" in reason

def test_no_bodies_scores_zero():
    assert service_stop.service_stop({"name": "X", "bodies": []}) == (0, "no body data")

def test_cannibalisation_rule():
    assert not service_stop.cannibalises({"Agriculture", "Refinery", "Tourism"})
    assert service_stop.cannibalises({"Industrial", "Agriculture"})
    assert service_stop.cannibalises({"HighTech", "Extraction"})
    assert not service_stop.cannibalises({"Industrial"})
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Score each cluster from: its root's `distanceToArrival` (shorter better), landable moons and summed known `ground_slots`, High Tech/Industrial-giving bodies, Earth-like/water/ammonia worlds (weighted up), rings, minus a penalty when `cannibalises(cluster economies)`; plus a bonus when another cluster can take High Tech (market before outfitting). The system score is the best cluster's, rounded to int. All weights in one module-level `WEIGHTS` dict, one comment each. Reason format: `"<Body kind> <short name> at <ls> ls: <n> landable moons, ~<slots> ground slots[, rings]; <economies joined by ' + '>"`; body kind from subType ("Gas giant", "Icy body", …), short name = body name minus the system name.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: colonisation service-stop score with reason`.

### Task 3 (hub): migration, import and routes

**Files:**
- Create: `sql/020_colonisation_service_stop.sql`
- Modify: `eddatahub/colonisation.py` (`UPSERT`, `BODY`, `_rows`, `search`, `system`)
- Test: `tests/test_colonisation.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: Task 1 `body_facts`, `clusters`; Task 2 `service_stop`.
- Produces: `colonisation_bodies` new columns `parent_id int, cluster int, rings bool, atmosphere bool, terraformable bool, geo bool, bio bool, tidally_locked bool, radius_km real, gravity_g real, temperature_k real, ground_slots smallint`; `colonisation_systems` new columns `service_score int, service_reason text`. `search()` rows gain `service_score`, `service_reason` and order by `service_score DESC NULLS LAST, score DESC, distance_ly`. `system()` bodies gain `body_id, parent_id, cluster, rings, ground_slots, terraformable, geo, bio` and the system gains `service_score, service_reason`.

- [ ] **Step 1: Write failing tests.** In `tests/test_colonisation.py`: load the Tucanae fixture through `colonisation.load(conn, [json.dumps(fixture)], "week")` (seed `region_systems` and a populated neighbour as existing tests do), then assert `service_score` is not NULL, body "3 a" has `ground_slots = 2` and `cluster` = body 3's id. A second test: a row inserted without service fields (as today) is returned by `search()` after a scored row. In `tests/test_web.py`: `/api/colonisation-system?id64=…` body dicts contain `ground_slots` and `cluster`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Migration with `SET LOCAL lock_timeout = '5s';` and `ALTER TABLE … ADD COLUMN` (all nullable, no index — see migration 019's lesson). Extend `UPSERT`/`BODY` and `_rows` from `body_facts`/`clusters`/`service_stop`.
- [ ] **Step 4: Run** the full hub suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: colonisation import stores body facts and service-stop score (migration 020)`.

### Task 4 (app): Service stop column, Design button

**Files:**
- Modify: `edc/ui/panels/colonisation_finder_dialog.py`
- Test: `tests/test_colonisation_finder_dialog.py`

**Interfaces:**
- Consumes: hub search rows `service_score: int|None`, `service_reason: str|None`.
- Produces: table column index 3 "Service stop" (Score moves to 4, every later column +1; default sort column 3 descending); `self._design_btn` (QPushButton "Design…", disabled until a row is selected). Task 6 connects it to `self._open_design(id64: int, name: str)`.

- [ ] **Step 1: Write failing tests:** a row with `service_score: 40, service_reason: "Gas giant 3 at 898 ls: …"` shows "40" in column 3 with the reason as tooltip; a row without those keys shows "" and sorts below it under the default sort; `_design_btn` is disabled before selection and enabled after `selectRow(0)`. Update existing tests' column indexes.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Missing keys via `.get` (hub not yet deployed). Add the button and its enable/disable only; Task 6 adds `_open_design` and connects the button's `clicked`.
- [ ] **Step 4: Run** the app suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: Find Systems shows the service-stop score`.

### Task 5 (app): build plan logic

**Files:**
- Create: `edc/core/colonisation_design.py`
- Test: `tests/test_colonisation_design.py`

**Interfaces:**
- Consumes: hub `/api/colonisation-system` dict (Task 3 shape).
- Produces: `plan_system(system: dict, primary_body: str, group: bool) -> dict` returning `{"poor": str|None, "steps": list[dict], "warnings": list[str], "note": str|None}`; each step `{"title": str, "body": str, "unlocks": list[str], "needs": str|None}`.

- [ ] **Step 1: Write failing tests** with hand-built system dicts in the Task 3 shape (copy body names/economies from the Tucanae fixture):

```python
def test_star_primary_is_poor():
    assert plan_system(TUC, "Tucanae Sector PY-R b4-1", False)["poor"].startswith("Primary slot on a star")

def test_solo_plan_on_gas_giant_3():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", False)
    assert p["poor"] is None
    assert [s["title"] for s in p["steps"]][:2] == ["Primary: Coriolis", "Comms or Relay installation"]
    assert "Universal Cartographics" in p["steps"][1]["unlocks"] and "Vista Genomics" in p["steps"][1]["unlocks"]

def test_group_plan_skips_comms_step():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", True)
    assert p["steps"][0]["title"] == "Primary: Ocellus"          # rings on body 3
    assert all(s["title"] != "Comms or Relay installation" for s in p["steps"])

def test_high_tech_goes_to_other_cluster():
    p = plan_system(TUC, "Tucanae Sector PY-R b4-1 3", False)
    ht = next(s for s in p["steps"] if s["title"] == "High Tech Hub")
    assert ht["body"].startswith("Tucanae Sector PY-R b4-1 4")   # cluster 4, not the primary's

def test_missing_body_details_says_so():
    assert plan_system({"bodies": [{"name": "A"}]}, "A", False)["poor"] == "Hub has no body details yet"
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the phase order from the spec (Primary → Comms/Relay → surface port on primary body → Mining Installation + Industrial Hub on a moon → High Tech Hub on another cluster or left out with note → optional growth), skipping satisfied steps; Solo → Coriolis, Group → Ocellus if the primary body has rings else Orbis, each with tonnage (Coriolis ≈ 70 kt, T3 ≈ 250 kt) and "4 weeks" text. Poor-pick thresholds in one `POOR` dict at the top (star primary; cluster with no landable moon of known slots > 0; primary farther than a set ls). Per-port warning via the cannibalisation rule (Global Constraints). `note` when the hub's `service_reason` names a different cluster ("best cluster is …").
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: colonisation build plan from body details`.

### Task 6 (app): System Design window

**Files:**
- Create: `edc/ui/panels/colonisation_design_dialog.py`
- Modify: `edc/ui/panels/colonisation_finder_dialog.py` (`_open_design`)
- Test: `tests/test_colonisation_design_dialog.py`

**Interfaces:**
- Consumes: Task 5 `plan_system`; `fetch_colonisation_system(url, id64, faction)`.
- Produces: `ColonisationDesignDialog(parent, hub_url: str, id64: int, name: str)`.

- [ ] **Step 1: Write failing tests:** with `fetch_colonisation_system` monkeypatched to the Tucanae dict, picking "… 3" in the primary-body combo renders the step titles in order; picking the star shows a red poor-pick banner and no steps; a dict without body details shows "Hub has no body details yet"; the Solo/Group toggle re-plans. Hub fetch runs off the GUI thread (reuse the finder's `_Worker`/`_start` pattern; QThreads kept referenced).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** in the app's dark style (`_TABLE_STYLE`, `_INPUT_STYLE`, `_BTN_STYLE` from the finder): primary-body combo (bodies grouped by cluster, hint "Find the flag in the system map's Architect View"), Solo/Group toggle, banner, steps table (Step, Body, Unlocks, Needs), warnings, sources footer with dates and "Controlling faction = the claim station's". Wire `_open_design`.
- [ ] **Step 4: Run** the app suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: colonisation System Design window`.

### Task 7: deploy, full import, live check

- [ ] **Step 1:** Push both repos (after Evan's go-ahead). Evan runs `sudo bash /opt/eddatahub/app/deploy/update.sh` (expects `applied: ['020_colonisation_service_stop.sql']`), then forces the full import (`colonisation-import --full`, ≈53 min; command per the hub's deploy notes).
- [ ] **Step 2:** Over SSH (`claude_ro`): `SELECT count(*), count(service_score) FROM colonisation_systems` — all rows scored; the three named systems in the required order.
- [ ] **Step 3:** Run the scratchpad live script against the hub (search, select Tucanae Sector PY-R b4-1, open Design, pick body 3) and inspect the screenshot.
- [ ] **Step 4:** Evan restarts the app and confirms in Find Systems and the Design window. Issue stays open until he does.
