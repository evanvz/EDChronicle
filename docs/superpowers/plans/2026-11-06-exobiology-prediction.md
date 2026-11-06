# Exobiology Prediction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show labelled possible genera/species and an "up to" value for biological bodies, rank them by value, and add one Overview line for a high value planet.

**Architecture:** A bundled rules file and one pure module, `edc/core/exo_predictor.py`, which turns `AppState` into `{body_name: BodyPrediction}`. `MainWindow` computes that once per refresh and hands it to the panels. Panels only render it; nothing is ever saved or written to `BioGenuses`.

**Tech Stack:** Python, PyQt6, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-06-exobiology-prediction-design.md`

## Global Constraints

- Run tests with `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`. Known failure, not ours: `tests/test_expansion_forecast_repo.py::test_presence_has_first_and_latest_reading`.
- Work on branch `feat/exobiology-prediction`, created from `feat/eddn-1.0.3`, so the app Evan runs keeps 1.0.3 while its in-game check is open. No pushes. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No schema changes, no network calls, no voice alert or toast.
- Guesses never reach `BioGenuses`, `state.bio_genuses`, `state.exo`, the DB or the codex data.
- New `.py` files start with the 3-line GPL header used in `edc/core/exo_values.py`.
- `edc/ui/main_window.py`, `edc/core/event_engine.py`, `edc/ui/panels/exploration_panel.py` change often: re-read the target lines before editing. Line numbers below are from 2026-11-06.
- Exobiology features are not done until Evan confirms them with live journal events.

## Review Focus

- A body with signals but no `Scan` facts (signals arrived first, EDDN/Spansh record): no prediction and no crash.
- Localised or empty spellings: `Carbon dioxide`, `None`, `No volcanism`, empty string. Must behave like the raw journal values.
- A sighting or `state.exo` species that's unknown, or carries a variant (`Stratum Tectonicas - Teal`): no crash, and real data still wins.
- `settings/exo_habitat.json` missing or corrupt: the app starts as today, logs it, and shows no predictions.
- More signals than possible genera, or a genus sampled to 3/3: no negative slots, `up_to` never below 0, finished body has no line.

---

### Task 1: Rules file and predictor core

**Files:**
- Create: `settings/exo_habitat.json`
- Create: `edc/core/exo_predictor.py`
- Create: `tests/test_exo_predictor.py`
- Modify: `THIRD_PARTY_NOTICES.md`
- Add to this commit: the spec and this plan

**Interfaces:**
- Consumes: `edc.core.exo_values.ExoValueTable` (`by_species[name].base_value`, `.genus`)
- Produces:

```python
@dataclass(frozen=True)
class BodyPrediction:
    possible: dict[str, list[tuple[str, int]]]  # genus -> [(species, base value)], best first; only genera with no real species
    up_to: int                                  # credits still to earn on this body

def load_rules(*paths: Path) -> list[dict] | None
def fits(rec: dict, ruleset: dict, stars: dict[int, dict], system_classes: set[str], fss_complete: bool) -> bool
def predict_body(rec, rules, values, stars, system_classes, fss_complete,
                 known_species: dict[str, str], finished_genera: set[str]) -> BodyPrediction | None
def predict_system(state, rules, values, sightings: dict[int, list]) -> dict[str, BodyPrediction]
def possible_text(pred: BodyPrediction) -> str
```

- [ ] **Step 1: Create the branch and generate the data file**

`git switch -c feat/exobiology-prediction`. Fetch `data/exobiology/species.json` from `uruskan/EliteNexus` (`gh api`) into the scratchpad and record the file's latest commit SHA. Using a throwaway script, not committed, write `settings/exo_habitat.json`:

```json
{"schema": "edchronicle.exobiology.habitat.v1",
 "meta": {"source": "https://github.com/uruskan/EliteNexus data/exobiology/species.json", "commit": "<sha>", "retrieved": "<date>", "licence": "GPL-3.0-or-later"},
 "species": [{"genus": "Aleoida", "species": "Aleoida Arcus", "codex_name": "$Codex_Ent_Aleoids_01_Name;", "rulesets": [], "sources": []}]}
```

Keep only entries with `rulesets` (expected 118). `species` comes from `full_name`, `codex_name` from `codex_name_pattern`. Rename to match our `exo_values.json`: species `Bark Mounds` to `Bark Mound`, `Radicoida Unica` to `Radicoida Unicus`; genus `Bark Mounds` to `Bark Mound`, `Sinuous Tubers` to `Sinuous Tuber`. The script prints any species whose `value` differs from our table. Expected: none; report anything else to Evan.

- [ ] **Step 2: Write failing tests in `tests/test_exo_predictor.py`**

Use real rules from `settings/exo_habitat.json` where named, otherwise small in-test rulesets.

```python
def test_data_file_every_species_has_a_value():  # all rules' species are in exo_values.json; len(rules) == 118
def test_missing_or_corrupt_file_returns_none(tmp_path):  # load_rules(missing) and load_rules(bad json) -> None
def test_aleoida_arcus_fits():  # Rocky body, CarbonDioxide, g 1.0 m/s2, 177 K, 2000 Pa, no volcanism
def test_each_bound_excludes():  # gravity/temp/pressure/atmosphere/body type/volcanism, one parametrised case each
def test_max_pressure_is_exclusive():  # p == max_pressure_atm -> False
def test_missing_value_skips_that_test():  # SurfaceTemperature None passes temp rules
def test_atmosphere_spellings():  # "CarbonDioxide", "Carbon dioxide", "carbon dioxide" all match; "", "None" = no atmosphere
def test_no_volcanism_spellings():  # "", "No volcanism" satisfy "none"; fail "required"
def test_star_anywhere_only_after_fss_complete():  # no match in stars: True while fss_complete False, False once True
def test_system_body_type_only_after_fss_complete():
def test_parent_star_needs_every_parent_scanned():  # Parents [{"Star": 1}, {"Star": 2}], only 1 known -> rule passes
def test_star_class_and_luminosity_matching():  # "A" matches A_BlueWhiteSuperGiant; ["B","IV"] matches IVab, not V; "D" matches DA
def test_untested_rule_types_pass():  # regions, region_ids, nebula, near_guardian_ruins, tuber_zones, system
def test_no_facts_no_prediction():  # empty PlanetClass or SurfaceGravity None -> predict_body returns None
def test_up_to_top_n_genera():  # 2 signals, genera best values 10/7/3 -> up_to 17, each genus once
def test_more_signals_than_genera():  # 5 signals, 2 genera -> sum of 2
def test_dss_limits_to_found_genera():  # BioGenuses ["X"] -> possible only X; up_to = best X
def test_known_species_uses_real_value_and_a_slot():  # 2 signals, X known at 1M, Y best 7, Z best 3 -> 8; X not in possible
def test_finished_genus_takes_slot_counts_zero():  # 2 signals, X finished, Y best 7, Z best 3 -> 7
def test_all_finished_up_to_zero():  # possible empty, up_to 0, possible_text == ""
def test_predict_system_sampled_beats_sighting():  # state.exo species differs from sighting -> state.exo value used
def test_predict_system_bad_names_ignored():  # sighting "Nonsense" ignored; "Stratum Tectonicas - Teal" resolves
def test_predict_system_skips_no_bio_bodies():
def test_guesses_not_written_to_state():  # deep copy state.bodies, bio_genuses, exo before; equal after
def test_possible_text():  # "Possible: Aleoida, Bacterium · up to 12.3M" before DSS
```

- [ ] **Step 3: Run, expect failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exo_predictor.py -q -p no:cacheprovider`
Expected: FAIL, `exo_predictor` not found.

- [ ] **Step 4: Implement `edc/core/exo_predictor.py`**

Rule semantics are in the spec's "Rule semantics" section. Pinned: `G = 9.797759`, `ATM = 101231.65625`. Normalise atmosphere with `re.sub(r"[^a-z]", "", s.lower())` on both sides, and treat `""`/`"none"` as no atmosphere. Lower-case volcanism and treat `"no volcanism"` as empty. System-wide star and body-type rules test only when `fss_complete` is true.

`predict_body` algorithm:

```text
if not PlanetClass or SurfaceGravity is None or BioSignals <= 0: return None
genera = {genus: [(species, value)...]} of species with any fitting ruleset, best value first
if BioGenuses: keep only those genera; slots = len(BioGenuses)  else: slots = BioSignals
real = known_species genera (unfinished) at real value; taken = len(real) + len(finished_genera)
remaining = genera minus known and finished
up_to = sum(real values) + sum(top max(0, slots - taken) of best value per remaining genus)
possible = remaining
```

Species absent from `values` count as value 0.

`predict_system` builds, per body with `BioSignals > 0`: `known_species` from `sightings[BodyID]` first, then overwritten by `state.exo` records for that `BodyID` with a `Species`; variants stripped at `" - "`; genus via `values.by_species`, names not found are ignored. `finished_genera` is `state.exo` records with `Samples >= 3`. `stars` is `getattr(state, "system_stars", {})`; `system_classes` is every `PlanetClass` in `state.bodies`. `rules` or `values` being `None` returns `{}`.

- [ ] **Step 5: Run tests, expect PASS**

Same command. Expected: all pass.

- [ ] **Step 6: Add credit to `THIRD_PARTY_NOTICES.md`**

EliteNexus (GPL-3.0-or-later), with underlying sources EDMC-BioScan (GPL-2.0-or-later), SrvSurvey (GPL-3.0), Canonn codex data; names `settings/exo_habitat.json`.

- [ ] **Step 7: Commit**

```bash
git add settings/exo_habitat.json edc/core/exo_predictor.py tests/test_exo_predictor.py THIRD_PARTY_NOTICES.md docs/superpowers/specs/2026-11-06-exobiology-prediction-design.md docs/superpowers/plans/2026-11-06-exobiology-prediction.md
git commit -m "feat: exobiology habitat rules and predictor"
```

### Task 2: Keep stars and Parents in state

**Files:**
- Modify: `edc/core/state.py:78-98`
- Modify: `edc/core/event_engine.py:484-487, 618-633, 1433-1435, 1468-1496`
- Test: `tests/test_exo_state_stars.py`

**Interfaces:**
- Produces: `state.system_stars: Dict[int, Dict[str, Any]]`, BodyID to `{"StarType": str, "Luminosity": str, "DistanceLS": float}`; body record key `"Parents"` (list, raw journal value). `predict_system` and `fits` read these; adjust `fits` so star records use these keys if Task 1 assumed otherwise.

- [ ] **Step 1: Write failing tests**

Follow how existing tests build an `EventEngine`.

```python
def test_star_scan_kept():  # Scan with StarType "K", BodyID 0 -> state.system_stars[0]["StarType"] == "K"; not in state.bodies
def test_planet_scan_keeps_parents():  # rec["Parents"] == [{"Star": 0}]
def test_fsdjump_clears_stars():  # system_stars empty after FSDJump
def test_location_new_system_clears_stars_and_fss_complete():  # fss_complete False too
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exo_state_stars.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add the `system_stars` field. Store stars just before the early return at `event_engine.py:1434`. Clear beside each `bio_genuses.clear()`. Set `fss_complete = False` in the `new_sys` branch near line 484; the FSDJump branch already does it (line 633). Add `"Parents": event.get("Parents") or []` to the body record.

- [ ] **Step 4: Run tests and the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`
Expected: only the known failure.

- [ ] **Step 5: Commit**

`git commit -m "feat: keep the system's stars and body Parents in state"` with the three files.

### Task 3: Exobiology tab

**Files:**
- Modify: `edc/ui/panels/exobiology_panel.py:143, 442-464, 511-530, 649, 720-765`
- Modify: `edc/ui/main_window.py:60, 2642, 7327, 7414`
- Test: `tests/test_exobiology_panel_possible.py`

**Interfaces:**
- Consumes: `load_rules`, `predict_system`, `BodyPrediction` from Task 1.
- Produces: `MainWindow._exo_predictions() -> dict[str, BodyPrediction]` (used by Tasks 4 and 5); `ExobiologyPanel.refresh(state, cfg, exo_values, canonn_poi=None, exo_predictions=None)`; module function `_row_sort_key(row, up_to_by_body) -> tuple`.

- [ ] **Step 1: Write failing tests**

Mirror the `QApplication` offscreen set-up in `tests/test_exobiology_canonn_body_matching.py`.

```python
def test_needs_dss_row_shows_possible_and_up_to():  # rendered text has "possible:" and "up to", status still NEEDS DSS
def test_canonn_hint_keeps_priority():  # Canonn species on the body -> no "possible:" for that row
def test_after_dss_lists_possible_species_and_fit_limited_top():  # one fitting species -> its value, not genus_max
def test_no_predictions_renders_as_today():  # exo_predictions=None -> same text as before
def test_rank_by_up_to_across_needs_dss_and_unscanned():  # 40M UNSCANNED sorts before 5M NEEDS DSS; COMPLETE stays last
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exobiology_panel_possible.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

- In the `NEEDS DSS` branch: when no Canonn hint and a prediction exists, species column `possible: <genus>, <genus>`, base column `up to <n>M`.
- In the DSS branch: for an unconfirmed genus, `pot` becomes the top value in `pred.possible[genus]` when present, otherwise today's `genus_max`. Species column `possible: <species>, ...`, base column `up to <value>`, only when not already a CODEX hint.
- Rendering: wrap text starting `possible:` or `up to` in a dimmer colour (`#888888`). Confirmed rows keep their style.
- `_row_sort_key`: `(rank, -samples, -up_to_by_body.get(body, 0))`, where `NEEDS DSS` and `UNSCANNED` share rank 10; other ranks unchanged.
- `MainWindow`: load rules beside `exo_values` at line 2642 (`load_rules(settings_base / "exo_habitat.json")`, stored as `self.exo_rules`). `_exo_predictions` calls `predict_system(self.state, self.exo_rules, self.exo_values, sightings)`, reusing the `_codex_sightings_cache` logic at lines 7474-7480; extract it into `_codex_sightings()` so both use it. Pass the result at lines 7327 and 7414. Wrap nothing else: a `None` rules file gives `{}`.

- [ ] **Step 4: Run tests and import check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exobiology_panel_possible.py tests/test_exobiology_canonn_body_matching.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: possible species and up-to value on the Exobiology tab"` with the changed files.

### Task 4: Exploration body cards

**Files:**
- Modify: `edc/ui/panels/exploration_panel.py:230, 577-583, 645-650, 825-835`
- Modify: `edc/ui/main_window.py:7353, 7408`
- Test: `tests/test_exploration_possible_exo.py`

**Interfaces:**
- Consumes: `possible_text(pred)` from Task 1; `MainWindow._exo_predictions()` from Task 3.
- Produces: `ExplorationPanel.refresh(state, cfg, planet_values, spansh_rings=None, edastro_poi=None, exo_predictions=None)`.

- [ ] **Step 1: Write failing tests**

```python
def test_card_shows_possible_line():  # card text has "Possible:" and "up to", dim style
def test_card_updates_when_prediction_changes():  # second refresh with a new prediction rebuilds the card
def test_no_prediction_no_line():  # exo_predictions=None -> no "Possible:"
def test_sort_order_unchanged():  # still by EstimatedValue
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exploration_possible_exo.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

Compute `exo_line = possible_text(pred)` per body. Append it as the last item of `signature` and the last parameter of `_build_body_card` (`exo_line=""`), so cards rebuild when it changes. Render it just after the genus badges at line 835 as a word-wrapped `QLabel` in `#888888`, transparent background, no border, only when non-empty. Pass `exo_predictions=self._exo_predictions()` at both call sites.

- [ ] **Step 4: Run tests**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: possible exobiology line on Exploration body cards"` with the changed files.

### Task 5: Overview line and threshold setting

**Files:**
- Modify: `edc/config.py:37, 202, 251`
- Modify: `edc/ui/main_window.py` (settings near lines 2995-3001 and 4263; `_refresh_hud` near lines 6180 and 6698)
- Modify: `edc/core/exo_predictor.py`
- Test: `tests/test_exo_overview_line.py`

**Interfaces:**
- Consumes: `MainWindow._exo_predictions()`, `BodyPrediction`.
- Produces: `cfg.exo_overview_alert_m: int = 30`; `high_value_line(predictions: dict[str, BodyPrediction], threshold_m: int) -> str` in `exo_predictor.py`.

- [ ] **Step 1: Write failing tests**

```python
def test_line_for_best_planet_only():  # two over the bar -> only highest; text contains 'href="exobiology"',
                                       # "🧬 High value exo planet: A 1, up to 41M"
def test_at_threshold_shows():  # up_to == 30_000_000, threshold 30
def test_below_threshold_empty():
def test_finished_planet_clears():  # up_to 0 -> ""
def test_config_default_and_roundtrip():  # default 30; a saved value reloads
def test_exo_high_value_m_unchanged():  # default still 2
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exo_overview_line.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

`high_value_line` returns `<a href="exobiology" style="color:#6BCB77; text-decoration:none;">🧬 High value exo planet: {body}, up to {m:.0f}M</a>` with the body HTML-escaped. It's kept out of the `"action:"` filter: in `_refresh_hud`, append it to `final_lines` after the PP action, the same way as `pp_txt`, so the count limits on action lines don't drop it. Add the setting at the three `config.py` places, mirroring `exo_high_value_m`. Add a slider labelled for the Overview alert, range 5-100, beside `exo_min_slider`, with a handler mirroring `_on_exo_min_changed`.

- [ ] **Step 4: Run all tests and start the app**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`
Expected: only the known failure. Then start the app and confirm the log has no new errors and the slider appears.

- [ ] **Step 5: Commit**

`git commit -m "feat: Overview line for a high value exobiology planet"` with the changed files.

### Task 6: Live confirmation (Evan)

No code unless a fault turns up.

- [ ] **Step 1: Evan restarts the app and FSS scans a system with biological signals**

Expected: Exobiology and Exploration show the count plus dim "possible" genera and "up to"; the best planet ranks first on Exobiology; a planet at 30M or more gets the silent Overview line, and clicking it opens the Exobiology tab.

- [ ] **Step 2: Evan DSS maps and samples one planet**

Expected: real genera replace guesses, the first sample shows the real species and value, and 3 of 3 drops it from "up to". Check the journal and log against what the app showed.

- [ ] **Step 3: Keep the issue open until Evan confirms**
