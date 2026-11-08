# Design My System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open the colonisation Design window for the current system, with a numbered and editable build order. Each build carries a Planned/Building/Complete status, stored locally and driven by construction depots. The planner never places a poor build.

**Architecture:**
- Planner rules stay pure in `edc/core/colonisation_planner.py`. `plan()` gains three things: Solo blocks Tier 3 ports, an economy check before each placement that leaves the slot empty, and pre-placed fixed steps.
- Saved choices live in two new `edhelper.db` tables behind Repository methods.
- Pure depot-to-status logic lives in a new `edc/core/colonisation_plan_status.py`.
- The existing `ColonisationDesignDialog` gains an optional `repo`. With a repo and a typed plan, its table becomes editable.
- A new panel button opens the dialog for the current system.

**Tech Stack:** Python 3, PyQt6, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-colonisation-my-system-design.md`

## Global Constraints

- Planner code stays pure (no Qt) in `edc/core/colonisation_planner.py`.
- Facility data comes only from `settings/colonisation_facilities.json`, loaded with `colonisation_facilities.load()`.
- Database: SQLite `edhelper.db` through the existing `persistence/database.py` `run_migrations` personal list and `persistence/repository.py`. Every new migration entry is idempotent (`CREATE TABLE IF NOT EXISTS`).
- Threads: a new Database per thread, and QThreads stay referenced. The dialog reads and writes the plan tables on the GUI thread through the panel's own `Repository`, the same way the panel already reads depots.
- Window style reuses `_BTN_STYLE`, `_INPUT_STYLE` and `_TABLE_STYLE` from `colonisation_finder_dialog`.
- Statuses are exactly `"Planned"`, `"Building"`, `"Complete"`.
- Left-empty reason text: `"left empty: {body short} market would get a third economy ({economies, sorted, comma-separated})"`.
- Solo blocks `dodec_starport` and `large_planetary_port` everywhere. The primary port rule is unchanged.
- Tests: `.venv/Scripts/python.exe -m pytest tests/<file> -q -p no:cacheprovider`. The full suite has 3 failures that already exist and aren't caused by this work: `test_eddatahub_ticks.py::test_hub_ticks_parsed_and_offline_is_none` and the 2 date-based tests in `test_expansion_forecast_repo.py`.
- No commits to `main` until Evan says so. Work on branch `feat/design-my-system`.

## Review Focus

1. A saved facility key that is missing from `colonisation_facilities.json`, for example after a data update. The step is shown red as `"unknown facility: <key>"`, with no crash. Pinned in Task 2.
2. A saved step whose body no longer exists, or whose slot index is at or above the body's current count. The step is shown red as `"slot no longer exists"` and uses no slot. Pinned in Task 2.
3. Design My System pressed before the game has reported a system, or with no EDDataHub URL. The button is disabled, and no dialog opens with id64 None. Pinned in Task 1.
4. Switching Solo to Group, or changing the type, keeps every stored step and status. Re-planning never deletes stored rows. Pinned in Task 5.
5. A system with several depots, where the primary depot completes. The primary turns Complete. Other depots stay unlinked until Evan links them, and are never linked automatically. Pinned in Task 4.

---

### Task 1: Design My System button

**Files:**
- Modify: `edc/ui/panels/colonisation_panel.py`: button next to `_find_btn` (~line 1174), the `eddatahub_url` setter (~1541), `refresh()` (~1305), and a new `_open_my_system_design()`
- Test: `tests/test_colonisation_my_system_button.py` (create)

**Interfaces:**
- Consumes: `ColonisationDesignDialog(parent, hub_url, id64, name, repo=None)` (the `repo` keyword is added in Task 5; until then call without it).
- Produces: `ColonisationPanel._my_system_btn: QPushButton`, `ColonisationPanel._design_dialog` (None until first open), `ColonisationPanel._open_my_system_design() -> None`.

- [ ] **Step 1: Write failing tests**

```python
# QApplication + ColonisationPanel(MagicMock()) as in tests/test_colonisation_finder_dialog.py::test_button_disabled_without_hub_url
def test_button_needs_hub_and_current_system():
    panel = ColonisationPanel(MagicMock())
    assert not panel._my_system_btn.isEnabled()
    panel.eddatahub_url = "http://hub"
    assert not panel._my_system_btn.isEnabled()          # no system yet
    panel.refresh(SimpleNamespace(system="HIP 109508", system_address=79196785019,
                                  system_x=None, system_y=None, system_z=None))
    assert panel._my_system_btn.isEnabled()

def test_button_opens_design_for_current_system(monkeypatch):
    # monkeypatch colonisation_design_dialog.ColonisationDesignDialog with a recorder class;
    # click -> recorder got (hub_url="http://hub", id64=79196785019, name="HIP 109508");
    # a second click with another system calls .load(id64, name) on the same instance.
```

- [ ] **Step 2: Run them.** `pytest tests/test_colonisation_my_system_button.py`. Expected: FAIL, because `_my_system_btn` doesn't exist.
- [ ] **Step 3: Implement.**
  - Add a `QPushButton("Design My System…")` beside `_find_btn`, using `_BTN_STYLE`.
  - Enable it only when `self._eddatahub_url` is set and `self._last_state` has a non-empty `system` and an int `system_address`. Re-evaluate this in the URL setter and in `refresh()`.
  - Tooltip when there's no hub: `"Needs EDDataHub (Settings → EDDataHub URL)"`. Tooltip when there's no system: `"Waiting for current system…"`.
  - `_open_my_system_design()` creates the dialog once, reuses it with `.load(id64, name)` after that, then calls `show/raise_/activateWindow`.
  - Extend `stop_finder_dialog()` to also call `self._design_dialog.stop()` when it exists.
- [ ] **Step 4: Run tests.** Expected: PASS. `tests/test_colonisation_finder_dialog.py` still passes.
- [ ] **Step 5: Commit.** `feat: Design My System button opens the design window for the current system`

### Task 2: Planner: Solo without Tier 3, no poor builds, fixed steps, numbering

**Files:**
- Modify: `edc/core/colonisation_planner.py`: `plan()` and its inner `place()`
- Test: `tests/test_colonisation_planner.py` (add tests and reuse `DRM_SYS` / `LCT_SYS`; existing tests must still pass, or be updated only where Solo now blocks T3 ports)

**Interfaces:**
- Produces:

```python
def plan(system: dict, slots: list[dict], primary_body: str, group: bool, kind: str,
         fixed: list[dict] | None = None) -> dict
# fixed item: {"facility": str, "body": str, "location": "orbital"|"surface", "slot_index": int,
#              "status": "Planned"|"Building"|"Complete"}
# each returned step gains: "n": int (1-based), "slot_index": int, "fixed": bool,
#                           "status": str ("Planned" for auto steps), "error": str | None
# return dict gains: "empty": list[{"body": str, "location": str, "reason": str}]
```

- [ ] **Step 1: Write failing tests**

```python
def test_solo_full_plan_has_no_tier3_ports():
    p = plan(LCT_SYS, slot_table(LCT_SYS, None), LCT_PRIMARY, False, "full")
    assert not {s["facility"] for s in p["steps"][1:]} & {"dodec_starport", "large_planetary_port"}

def test_group_full_plan_still_places_tier3_ports():
    p = plan(LCT_SYS, slot_table(LCT_SYS, None), LCT_PRIMARY, True, "full")
    assert {s["facility"] for s in p["steps"]} & {"dodec_starport", "large_planetary_port"}

def test_no_step_gives_a_market_a_third_economy():
    # for both group values on LCT and DRM: no warning line containing "a third economy gets cannibalised"
    # and every p["empty"] reason starts with "left empty: "

def test_steps_are_numbered_in_order():
    p = _drm("full")
    assert [s["n"] for s in p["steps"]] == list(range(1, len(p["steps"]) + 1))
    assert p["steps"][0]["facility"] == "coriolis_starport" and p["steps"][0]["n"] == 1

def test_fixed_steps_placed_first_in_status_order():
    fixed = [{"facility": "mining_settlement_medium", "body": f"{DRM} 2", "location": "surface", "slot_index": 0, "status": "Planned"},
             {"facility": "comms_installation", "body": f"{DRM} 1", "location": "orbital", "slot_index": 1, "status": "Complete"}]
    p = plan(DRM_SYS, slot_table(DRM_SYS, DRM_RAVEN), DRM_PRIMARY, False, "full", fixed)
    assert [s["facility"] for s in p["steps"][1:3]] == ["comms_installation", "mining_settlement_medium"]
    assert p["steps"][1]["fixed"] and p["steps"][1]["status"] == "Complete"
    assert all(not s["fixed"] for s in p["steps"][3:])

def test_fixed_primary_row_sets_primary_status_only():
    fixed = [{"facility": "coriolis_starport", "body": DRM_PRIMARY, "location": "orbital", "slot_index": 0, "status": "Building"}]
    p = plan(DRM_SYS, slot_table(DRM_SYS, DRM_RAVEN), DRM_PRIMARY, False, "full", fixed)
    assert p["steps"][0]["status"] == "Building"
    assert sum(s["facility"] == "coriolis_starport" for s in p["steps"]) == 1

def test_fixed_step_on_missing_slot_is_red_and_takes_nothing():
    fixed = [{"facility": "comms_installation", "body": f"{DRM} 9", "location": "orbital", "slot_index": 0, "status": "Planned"},
             {"facility": "comms_installation", "body": f"{DRM} 2", "location": "orbital", "slot_index": 5, "status": "Planned"}]
    p = plan(DRM_SYS, slot_table(DRM_SYS, DRM_RAVEN), DRM_PRIMARY, False, "full", fixed)
    assert [s["error"] for s in p["steps"][1:3]] == ["slot no longer exists"] * 2

def test_fixed_unknown_facility_is_red_not_a_crash():
    fixed = [{"facility": "no_such_thing", "body": f"{DRM} 2", "location": "orbital", "slot_index": 0, "status": "Planned"}]
    p = plan(DRM_SYS, slot_table(DRM_SYS, DRM_RAVEN), DRM_PRIMARY, False, "full", fixed)
    assert p["steps"][1]["error"] == "unknown facility: no_such_thing"

def test_fixed_step_missing_requirement_keeps_its_place_with_error():
    # fixed refinery_hub (requires a T2 source not yet built) with only the primary before it:
    # step present, error startswith "needs ", and points not deducted below zero (t2/t3 shown as computed)
```

- [ ] **Step 2: Run them.** Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
  - **Solo:** inside `place()`, return False for `dodec_starport` and `large_planetary_port` when `not group`.
  - **Economy check before placing:** inside `place()`, compute the economies of the facility's body using the same set the end-of-plan check builds. That is the body's own `economies`, plus every economy already placed on that body (`f["economy"] or _HUB_ECON.get(key)`), plus the new one. Drop `{"Colony", "Terraforming"}` and normalise `"Hightech"` to `"HighTech"`. If `_clash(set)` is true:
    - record `empty[(body, loc)] = reason` with the Global Constraints reason text;
    - return False.

    After all passes, emit `"empty"` for each recorded key where `free[(body, loc)] > 0`.
  - **Fixed steps:** after the primary, check whether a fixed item is the primary itself (same `facility == pkey` and body `primary_body`). If so, copy its status onto the primary step.
  - **Placing fixed steps:** place the rest in groups, Complete, then Building, then Planned. Within a group, repeat until there's no progress, placing items whose `requires` are met. Leftovers get `error = "needs " + " or ".join(requires names)`. Fixed placement skips the CP-balance and economy checks (Evan chose it), but still updates balance, stats and slots.
  - **Fixed-step validity:** a missing body, or `slot_index >= original count` for that (body, location), gives `error="slot no longer exists"`, and the step uses no slot. A facility key not in `fac` gives `error="unknown facility: <key>"`, and the step uses no slot or stats.
  - **slot_index for auto steps:** the next unused index per (body, location), counting indices already taken by fixed steps.
  - **Numbering:** set `n` last, by list position.
- [ ] **Step 4: Run the whole planner file plus `tests/test_colonisation_design_dialog.py`.** Expected: PASS. If an old test asserted a Dodec in a solo plan, change it to `group=True` and note that in the commit message.
- [ ] **Step 5: Commit.** `feat: planner leaves poor slots empty, solo builds no tier 3 ports, honours fixed steps`

### Task 3: Plan storage

**Files:**
- Modify: `persistence/database.py`: two entries appended to `personal_migrations`
- Modify: `persistence/repository.py`: four methods next to `get_colonisation_depots` (~line 2877)
- Test: `tests/test_colonisation_plan_repo.py` (create; reuse the `_repo(tmp_path)` helper shape from `tests/test_expansion_forecast_repo.py`)

**Interfaces:**
- Produces:

```sql
CREATE TABLE IF NOT EXISTS colonisation_plan_steps (
  system_address INTEGER NOT NULL, body_name TEXT NOT NULL, location TEXT NOT NULL,
  slot_index INTEGER NOT NULL, facility TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Planned',
  market_id INTEGER, updated_at TEXT NOT NULL,
  PRIMARY KEY (system_address, body_name, location, slot_index))
CREATE TABLE IF NOT EXISTS colonisation_plan_settings (
  system_address INTEGER PRIMARY KEY, kind TEXT, grp INTEGER NOT NULL DEFAULT 0,
  primary_body TEXT, updated_at TEXT NOT NULL)
```

```python
def get_colonisation_plan(self, system_address: int) -> dict
    # {"settings": {"kind": str|None, "group": bool, "primary_body": str|None} | None,
    #  "steps": [{"facility","body","location","slot_index","status","market_id"}]}
def save_colonisation_plan_step(self, system_address: int, body: str, location: str, slot_index: int,
                                facility: str, status: str, market_id: int | None = None) -> None   # upsert
def delete_colonisation_plan_step(self, system_address: int, body: str, location: str, slot_index: int) -> None
def save_colonisation_plan_settings(self, system_address: int, kind: str | None, group: bool,
                                    primary_body: str | None) -> None                                  # upsert
```

- [ ] **Step 1: Write failing tests.**
  - `test_plan_round_trip`: save two steps and the settings, then `get` returns them. `"body"` is mapped from `body_name`, and `group` is a bool.
  - `test_upsert_replaces_same_slot`: saving the same key twice keeps one row with the newest facility and status.
  - `test_delete_removes_only_that_slot`.
  - `test_other_system_isolated`.
  - `test_empty_system_returns_none_settings_and_no_steps`.
- [ ] **Step 2: Run them.** Expected: FAIL, because the methods don't exist.
- [ ] **Step 3: Implement.** Append the two DDL strings to `personal_migrations`. Use `ON CONFLICT ... DO UPDATE` upserts, with `updated_at = datetime.now(timezone.utc).isoformat()`. Commit after each write, like `save_colonisation_depot_visit`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat: local storage for colonisation build plans`

### Task 4: Depot-driven status (pure)

**Files:**
- Create: `edc/core/colonisation_plan_status.py`
- Test: `tests/test_colonisation_plan_status.py` (create)

**Interfaces:**
- Consumes: depot dicts as returned by `Repository.get_colonisation_depots()` (keys `id`, `market_id`, `system_address`, `station_name`, `progress`, `complete`). Stored step dicts as in Task 3.
- Produces:

```python
def primary_depot(depots: list[dict], system_address: int) -> dict | None
    # this system's depot with the lowest id (the colonisation ship is always a system's first depot)
def status_updates(stored: list[dict], depots: list[dict], system_address: int,
                   primary: dict) -> list[dict]
    # primary: {"facility","body","location":"orbital","slot_index":0}
    # returns step dicts to save (same keys as Task 3 steps), never deletions:
    #  - no stored row for the primary and primary_depot exists -> primary row, market_id set,
    #    status "Complete" if depot complete else "Building"
    #  - any stored row with market_id whose depot is now complete and status != "Complete" -> same row, status "Complete"
def unlinked_depots(stored: list[dict], depots: list[dict], system_address: int) -> list[dict]
    # this system's depots whose market_id no stored row references, excluding primary_depot
```

- [ ] **Step 1: Write failing tests.**
  - `test_first_depot_becomes_building_primary`
  - `test_primary_turns_complete_when_depot_completes`
  - `test_manual_status_on_unlinked_row_untouched`
  - `test_linked_site_turns_complete`
  - `test_other_systems_depots_ignored`
  - `test_second_depot_is_unlinked_not_auto_linked`. This one is Review Focus 5: two depots, the primary is complete, and the second shows in `unlinked_depots` and is absent from `status_updates`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** as pure functions with no Qt and no DB.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat: construction depots drive colonisation plan status`

### Task 5: Editable Design window

**Files:**
- Modify: `edc/ui/panels/colonisation_design_dialog.py`: `__init__` (add `repo=None`), table setup (~line 87), `_on_loaded`, `_replan` (~350-406), new handlers
- Modify: `edc/ui/panels/colonisation_panel.py`: `_open_my_system_design` passes `repo=self._repo`
- Test: `tests/test_colonisation_design_dialog.py` (add tests; reuse its `_dialog` / `_pick` helpers, give them an optional repo, and use a real `Repository` on `tmp_path` built like Task 3's tests)

**Interfaces:**
- Consumes:
  - `plan(..., fixed=...)` and the step keys from Task 2;
  - the Repository methods from Task 3;
  - `primary_depot`, `status_updates` and `unlinked_depots` from Task 4;
  - `Repository.get_colonisation_depots()`.
- Produces: `ColonisationDesignDialog(parent, hub_url, id64, name, repo=None)`. With `repo is None` (the finder path), behaviour is today's plus the # column.

**Behaviour:**
- **Table:** the table becomes 8 columns, `["#", "Step", "Body", "Status", "Unlocks", "Needs", "Points", ""]`. # is `n`.
  - The template path fills # with 1..N and leaves Status and the last column empty.
- **Editable typed plan:** the table is editable only when `repo` is set and the typed plan is active.
  - **Step:** a `QComboBox` with every facility key whose `location` equals the step's location, showing `fac["name"]`.
  - **Status:** a `QComboBox` with Planned/Building/Complete.
  - **Last column:** a "Reset" button, shown only on `fixed` rows that aren't the primary.
- **Saving edits:**
  - Changing Step or Status saves the row through `save_colonisation_plan_step`, with the step's body, location and slot_index, then re-plans.
  - Reset calls `delete_colonisation_plan_step`, then re-plans.
  - The primary's Step combo is disabled; it follows Solo/Group.
- **Error rows:** rows with `error` get the error in Needs and red foreground (`#ff6b6b`).
- **Empty slots:** each `p["empty"]` entry is listed after the numbered rows. These rows have no number, the text `left empty` with the reason in Needs, a grey foreground, and a Step combo. Picking a facility saves it as a Planned fixed step at the next slot_index for that body/location, then re-plans.
- **Depots:**
  - Under the table, show a "Construction sites" box. For each `unlinked_depots()` entry, show a label `"{station_name} — {progress*100:.1f}%"`, a combo of numbered non-primary rows (`"#{n} {title} — {body short}"`), and a "Link" button.
  - Link saves that row with `market_id` and status Building, then re-plans.
- **Settings:**
  - On load with a repo, apply `status_updates()` (saving each), and restore `get_colonisation_plan().settings` into the primary combo, Solo/Group and the type combo, before the first `_replan`.
  - Any change to those three widgets calls `save_colonisation_plan_settings`.
  - Changing them never deletes stored steps (Review Focus 4).

- [ ] **Step 1: Write failing tests**

```python
def test_hash_column_numbers_rows(monkeypatch): ...            # template path: col 0 == "1","2",...
def test_typed_plan_with_repo_has_step_and_status_selectors(monkeypatch, tmp_path): ...
def test_changing_status_persists_and_survives_reload(monkeypatch, tmp_path): ...   # new dialog, same repo -> combo shows Complete
def test_reset_removes_fixed_row(monkeypatch, tmp_path): ...
def test_switching_solo_group_keeps_stored_steps(monkeypatch, tmp_path): ...       # Review Focus 4
def test_settings_restored_on_reopen(monkeypatch, tmp_path): ...
def test_unlinked_depot_listed_and_link_sets_building(monkeypatch, tmp_path): ...
def test_primary_depot_sets_primary_building(monkeypatch, tmp_path): ...
def test_finder_path_without_repo_has_no_selectors(monkeypatch): ...
```

  These need a fixture system whose every body has confirmed slots, so the typed path runs. Build it from `TUC` in the same file, with `orbital_slots` and `surface_slots` set on every body. Use the existing `_confirmed()` rule.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the behaviour above. Keep `_replan()` the single place that rebuilds the table. Block combo signals while filling, so filling never triggers a save.
- [ ] **Step 4: Run the tests.** Run `tests/test_colonisation_design_dialog.py`, `tests/test_colonisation_finder_dialog.py`, `tests/test_colonisation_my_system_button.py`, then the full suite. Expected: PASS, apart from the 3 known failures.
- [ ] **Step 5: Run the app** (`.venv/Scripts/python.exe main.py`; Evan's running copy must be closed first, one instance only). Open Design My System at HIP 109508 and confirm:
  - the window opens;
  - step 1 is the Coriolis on A 8 b, with status Building;
  - with Full build and Solo, there's no Dodec.

  Take a screenshot for Evan.
- [ ] **Step 6: Commit.** `feat: editable numbered build order with status in the colonisation design window`
