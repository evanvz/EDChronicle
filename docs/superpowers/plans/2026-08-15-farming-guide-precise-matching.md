# Farming Guide Precise Live Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Intel tab's free-text keyword guessing for live farming-guide matches with curated, precise data — fixing real false positives (HGE Pharmaceutical Isolators wrongly matching Boom, High Wake Scans wrongly matching Anarchy) and a false negative (Pirate Attack settlements can't match Civil Unrest/Infrastructure Failure at all today) — and show only the specific matched material(s) for entries with per-material state data, instead of a generic entry-level pointer.

**Architecture:** `_get_system_opportunities`/`_entry_matches_system` move out of `IntelPanel` into module-level functions (testable without Qt, matching this codebase's established `_format_forecast()`-style pattern). Matching becomes data-driven: each guide entry either carries an explicit `state_tags` list (curated in `settings/elite_farming_locations.json`) or, for the one entry with per-material `examples[]`, derives tags from each example's own state text. The renderer shows only the specific matched example(s) when present.

**Tech Stack:** Python 3, PyQt6 (unaffected — no Qt-level changes), pytest.

## Global Constraints

- Do not touch `FarmingLocations.get_for_system()` or the exact system-name matching path — unrelated, already correct.
- Do not add a voice announcement for farming matches — explicitly deferred to a separate future pass per the design spec.
- Do not touch any guide entry beyond the 5 getting `state_tags` added. Do not add `state_tags` to "High Wake Scans" (it should never live-match). Do not modify the HGE manufactured entry's existing `examples[]`.
- New module-level functions must be importable and callable without constructing a `QApplication` or any `QWidget` — this is why they move out of the `IntelPanel` class.

---

### Task 1: Precise live matching — tags, guide data, matching logic, rendering

**Files:**
- Modify: `edc/ui/panels/intel_panel.py`
- Modify: `edc/core/farming_locations.py`
- Modify: `settings/elite_farming_locations.json`
- Test: `tests/test_farming_guide_matching.py` (new)

**Interfaces:**
- Produces: `_get_system_opportunities(state) -> set[str]`, `_state_text_to_tags(state_text: str) -> set[str]`, `_entry_matches_system(loc: dict, tags: set[str]) -> set[str]` — all module-level functions in `edc/ui/panels/intel_panel.py`. `FarmingLocations`-loaded records gain an optional `state_tags: list[str]` key (only present when the source JSON entry had a non-empty `state_tags` array).
- Consumes: nothing from other tasks (this is the only task).

- [ ] **Step 1: Write the failing tests**

Read `edc/ui/panels/intel_panel.py` and `edc/core/farming_locations.py` in full before writing tests, to confirm current exact state (both files have been touched multiple times this session; line numbers in this plan are illustrative, not authoritative).

Create `tests/test_farming_guide_matching.py`:

```python
"""Tests for the Intel tab's live farming-guide matching -- pure
functions, no Qt/QApplication needed (matches
tests/test_active_war_opponent.py's pattern of importing panel-module
free functions directly)."""
from types import SimpleNamespace

import pytest

from edc.core.farming_locations import FarmingLocations
from edc.ui.panels.intel_panel import (
    _get_system_opportunities,
    _entry_matches_system,
    _state_text_to_tags,
)


def _state(government="", allegiance="", security="", economy="", factions=None):
    return SimpleNamespace(
        system_government=government,
        system_allegiance=allegiance,
        system_security=security,
        system_economy=economy,
        factions=factions or [],
    )


# --- _get_system_opportunities: new tags ---

def test_civil_unrest_tag_from_active_states():
    state = _state(factions=[
        {"FactionState": "None", "ActiveStates": [{"State": "CivilUnrest", "Trend": 0}]}
    ])
    assert "civil_unrest" in _get_system_opportunities(state)


def test_infrastructure_failure_tag_from_active_states():
    state = _state(factions=[
        {"FactionState": "None", "ActiveStates": [{"State": "InfrastructureFailure", "Trend": 0}]}
    ])
    assert "infrastructure_failure" in _get_system_opportunities(state)


def test_empire_tag_from_allegiance():
    state = _state(allegiance="Empire")
    assert "empire" in _get_system_opportunities(state)


def test_federation_tag_from_allegiance():
    state = _state(allegiance="Federation")
    assert "federation" in _get_system_opportunities(state)


def test_empty_state_produces_no_tags():
    assert _get_system_opportunities(_state()) == set()


# --- _state_text_to_tags ---

@pytest.mark.parametrize("text,expected", [
    ("Outbreak", {"outbreak"}),
    ("Imperial allegiance / any state", {"empire"}),
    ("Federal allegiance / any state", {"federation"}),
    ("War / Civil War", {"war"}),
    ("Boom", {"boom"}),
    ("Something Unrecognized", set()),
])
def test_state_text_to_tags(text, expected):
    assert _state_text_to_tags(text) == expected


# --- _entry_matches_system ---

def test_state_tags_entry_matches_overlapping_live_tag():
    loc = {"name": "HGE Pharmaceutical Isolators", "state_tags": ["outbreak"]}
    assert _entry_matches_system(loc, {"outbreak"}) == {"outbreak"}


def test_hge_pharmaceutical_isolators_no_longer_matches_boom():
    # Regression test for the original bug: this entry's text contains
    # "hge"/"high grade", which the OLD keyword search wrongly matched
    # against the boom tag. It must only match outbreak now.
    loc = {"name": "HGE Pharmaceutical Isolators", "state_tags": ["outbreak"]}
    assert _entry_matches_system(loc, {"boom"}) == set()


def test_high_wake_scans_never_matches_anything():
    # Regression test for the original bug: this entry has no
    # state_tags at all (its "wake scan" text accidentally matched the
    # OLD anarchy keyword search). No state_tags + no examples means it
    # never live-matches, regardless of live tags.
    loc = {"name": "High Wake Scans", "method": "Scan high wakes in busy systems"}
    assert _entry_matches_system(loc, {"anarchy", "boom", "war"}) == set()


def test_hge_manufactured_entry_matches_only_the_relevant_example():
    loc = {
        "name": "High Grade Emissions (HGE)",
        "examples": [
            {"material": "Pharmaceutical Isolators", "state": "Outbreak"},
            {"material": "Imperial Shielding", "state": "Imperial allegiance / any state"},
            {"material": "Core Dynamics Composites", "state": "Federal allegiance / any state"},
            {"material": "Military Grade Alloys", "state": "War / Civil War"},
            {"material": "Proto Heat Radiators", "state": "Boom"},
        ],
    }
    assert _entry_matches_system(loc, {"boom"}) == {"boom"}


# --- FarmingLocations loader: state_tags round-trip ---

def test_loader_carries_state_tags_through(tmp_path):
    data = {
        "farming_locations": {
            "encoded": [
                {
                    "name": "HGE Pharmaceutical Isolators",
                    "method": "Search Outbreak systems for HGEs",
                    "key_materials": ["Pharmaceutical Isolators"],
                    "state_tags": ["outbreak"],
                }
            ]
        }
    }
    import json
    (tmp_path / "elite_farming_locations.json").write_text(json.dumps(data), encoding="utf-8")

    fl = FarmingLocations(tmp_path)
    records = fl._records
    assert len(records) == 1
    assert records[0]["state_tags"] == ["outbreak"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_farming_guide_matching.py -v`
Expected: FAIL — `ImportError` on `_get_system_opportunities`/`_entry_matches_system`/`_state_text_to_tags` (they don't exist as module-level functions yet), plus `records[0]["state_tags"]` KeyError once import is fixed manually to test in isolation.

- [ ] **Step 3: Move `_get_system_opportunities` out of `IntelPanel`, add 4 new tags**

In `edc/ui/panels/intel_panel.py`, find the current method:

```python
    def _get_system_opportunities(self, state):
        """
        Returns a set of tags describing what farming
        opportunities exist in the current system.
        """
        tags = set()

        # Allegiance/Government
        govt = str(getattr(state, "system_government", "") or "").lower()
        alleg = str(getattr(state, "system_allegiance", "") or "").lower()
        sec = str(getattr(state, "system_security", "") or "").lower()
        econ = str(getattr(state, "system_economy", "") or "").lower()

        if "anarchy" in govt:
            tags.add("anarchy")
        if "low" in sec:
            tags.add("low_security")
        if "high tech" in econ or "hightech" in econ:
            tags.add("high_tech")
        if "military" in econ:
            tags.add("military")
        if "industrial" in econ:
            tags.add("industrial")

        # Faction active states
        for f in (getattr(state, "factions", None) or []):
            if not isinstance(f, dict):
                continue
            active = f.get("ActiveStates") or []
            faction_state = str(f.get("FactionState") or "").lower()
            all_states = [faction_state]
            for st in active:
                if isinstance(st, dict):
                    all_states.append(
                        str(st.get("State") or "").lower()
                    )
            for s in all_states:
                if "boom" in s:
                    tags.add("boom")
                if "war" in s or "civil war" in s:
                    tags.add("war")
                if "outbreak" in s:
                    tags.add("outbreak")
                if "pirate" in s:
                    tags.add("pirate_attack")
                if "election" in s:
                    tags.add("election")
                if "expansion" in s:
                    tags.add("expansion")

        return tags
```

Delete it from inside the class. Add this as a module-level function instead — place it near the top of the file, directly after the imports/`log = logging.getLogger(...)` line and before the `class IntelPanel(QWidget):` line:

```python
def _get_system_opportunities(state):
    """
    Returns a set of tags describing what farming opportunities exist
    in the current system, from live game state. Module-level (not a
    method) so it's testable without a QApplication.
    """
    tags = set()

    # Allegiance/Government
    govt = str(getattr(state, "system_government", "") or "").lower()
    alleg = str(getattr(state, "system_allegiance", "") or "").lower()
    sec = str(getattr(state, "system_security", "") or "").lower()
    econ = str(getattr(state, "system_economy", "") or "").lower()

    if "anarchy" in govt:
        tags.add("anarchy")
    if "low" in sec:
        tags.add("low_security")
    if "high tech" in econ or "hightech" in econ:
        tags.add("high_tech")
    if "military" in econ:
        tags.add("military")
    if "industrial" in econ:
        tags.add("industrial")
    if "empire" in alleg:
        tags.add("empire")
    if "federation" in alleg:
        tags.add("federation")

    # Faction active states
    for f in (getattr(state, "factions", None) or []):
        if not isinstance(f, dict):
            continue
        active = f.get("ActiveStates") or []
        faction_state = str(f.get("FactionState") or "").lower()
        all_states = [faction_state]
        for st in active:
            if isinstance(st, dict):
                all_states.append(
                    str(st.get("State") or "").lower()
                )
        for s in all_states:
            if "boom" in s:
                tags.add("boom")
            if "war" in s or "civil war" in s:
                tags.add("war")
            if "outbreak" in s:
                tags.add("outbreak")
            if "pirate" in s:
                tags.add("pirate_attack")
            if "election" in s:
                tags.add("election")
            if "expansion" in s:
                tags.add("expansion")
            if "civilunrest" in s:
                tags.add("civil_unrest")
            if "infrastructurefailure" in s:
                tags.add("infrastructure_failure")

    return tags
```

(`"civilunrest"`/`"infrastructurefailure"` — no separator — matches this codebase's established casing for these exact `ActiveStates` values, confirmed against `persistence/repository.py:1886,1888` and `edc/ui/panels/player_faction_panel.py:136,161`.)

- [ ] **Step 4: Add `_state_text_to_tags` and replace `_entry_matches_system`**

Find the current method:

```python
    def _entry_matches_system(self, loc, tags):
        """
        Returns True if this farming entry is relevant
        to the current system based on active tags.
        """
        name   = str(loc.get("name") or "").lower()
        method = str(loc.get("method") or "").lower()
        combined = name + " " + method

        if "boom" in tags and any(
            k in combined for k in ["boom", "hge", "high grade"]
        ):
            return True
        if "war" in tags and any(
            k in combined for k in ["war", "conflict", "cz", "combat zone"]
        ):
            return True
        if "outbreak" in tags and "outbreak" in combined:
            return True
        if "anarchy" in tags and any(
            k in combined for k in ["anarchy", "high wake", "wake scan"]
        ):
            return True
        if "low_security" in tags and any(
            k in combined for k in ["low", "anarchy", "pirate"]
        ):
            return True
        if "pirate_attack" in tags and "pirate" in combined:
            return True
        return False
```

Delete it from inside the class. Add these two module-level functions directly after `_get_system_opportunities`:

```python
_STATE_TEXT_TAGS = {
    "outbreak": "outbreak",
    "boom": "boom",
}


def _state_text_to_tags(state_text: str) -> set:
    """
    Maps an examples[].state free-text value (from the farming guide's
    HGE entry) to the live-tag vocabulary _get_system_opportunities()
    produces. Deliberately narrow -- covers only the known state-text
    variants this guide's data actually uses, not a general parser.
    """
    s = (state_text or "").lower()
    tags = set()
    for key, tag in _STATE_TEXT_TAGS.items():
        if key in s:
            tags.add(tag)
    if "war" in s:
        tags.add("war")
    if "imperial" in s:
        tags.add("empire")
    if "federal" in s:
        tags.add("federation")
    return tags


def _entry_matches_system(loc: dict, tags: set) -> set:
    """
    Returns the subset of `tags` this entry actually matches, driven by
    curated data (loc["state_tags"], or -- for entries with an
    examples[] list -- each example's own state mapped via
    _state_text_to_tags()) -- never free-text keyword guessing against
    the entry's name/method. Empty set means no live match (the entry
    may still appear via an exact system/body name match, a separate,
    unrelated path in FarmingLocations.get_for_system()).
    """
    examples = loc.get("examples")
    if isinstance(examples, list) and examples:
        matched = set()
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            matched |= _state_text_to_tags(ex.get("state") or "") & tags
        return matched

    entry_tags = set(loc.get("state_tags") or [])
    return entry_tags & tags
```

- [ ] **Step 5: Run tests to verify the pure-function tests now pass**

Run: `pytest tests/test_farming_guide_matching.py -v`
Expected: the tests for `_get_system_opportunities`, `_state_text_to_tags`, and `_entry_matches_system` PASS. The loader test (`test_loader_carries_state_tags_through`) still FAILS at this point (Step 6 not done yet) — confirm the failure is specifically about `state_tags` missing from the loaded record, not an import error.

- [ ] **Step 6: Update `refresh()`'s call sites in `IntelPanel`**

Read `refresh()` fresh — the relevant block currently looks like:

```python
                all_records = getattr(farming_locations, "_records", []) or []
                opportunities = self._get_system_opportunities(state)
                # Exact system name matches
                by_system = farming_locations.get_for_system(sys_name) if sys_name else []
                seen_ids = {id(r) for r in by_system}
                # State-tag matches (boom/war/outbreak etc.)
                state_matches = [
                    r for r in all_records
                    if isinstance(r, dict)
                    and id(r) not in seen_ids
                    and self._entry_matches_system(r, opportunities)
                ]
                farm_entries = by_system + state_matches
```

Replace with:

```python
                all_records = getattr(farming_locations, "_records", []) or []
                opportunities = _get_system_opportunities(state)
                # Exact system name matches
                by_system = farming_locations.get_for_system(sys_name) if sys_name else []
                seen_ids = {id(r) for r in by_system}
                # State-tag matches (boom/war/outbreak etc.) -- entries
                # with an examples[] list only show the specific
                # example(s) whose own state is actually live, not the
                # whole entry.
                state_matches = []
                for r in all_records:
                    if not isinstance(r, dict) or id(r) in seen_ids:
                        continue
                    matched_tags = _entry_matches_system(r, opportunities)
                    if not matched_tags:
                        continue
                    entry = r
                    if isinstance(r.get("examples"), list):
                        entry = dict(r)
                        entry["_matched_examples"] = [
                            ex for ex in r["examples"]
                            if isinstance(ex, dict)
                            and _state_text_to_tags(ex.get("state") or "") & opportunities
                        ]
                    state_matches.append(entry)
                farm_entries = by_system + state_matches
```

Grep the rest of `intel_panel.py` for any other `self._get_system_opportunities` or `self._entry_matches_system` call sites (there should be none beyond this block, but confirm) and update them the same way if found.

- [ ] **Step 7: Add the `_matched_examples` rendering branch to `_farm_entry_html`**

Read `_farm_entry_html` fresh. Find the existing `if method:` block:

```python
        if method:
            line += (
                f'<br><span style="color:#6BCB77;font-size:12px;">'
                f'&nbsp;&nbsp;⚙ {self._esc(method)}</span>'
            )
        if note:
```

Insert a new block between them:

```python
        if method:
            line += (
                f'<br><span style="color:#6BCB77;font-size:12px;">'
                f'&nbsp;&nbsp;⚙ {self._esc(method)}</span>'
            )
        matched_examples = loc.get("_matched_examples") or []
        if matched_examples:
            for ex in matched_examples:
                mat = str(ex.get("material") or "")
                st = str(ex.get("state") or "")
                if not mat:
                    continue
                line += (
                    f'<br><span style="color:#FFD93D;font-size:12px;">'
                    f'&nbsp;&nbsp;⚡ {self._esc(mat)}'
                    + (f' — {self._esc(st)}' if st else '')
                    + '</span>'
                )
        if note:
```

- [ ] **Step 8: Add `state_tags` normalization to `FarmingLocations._load()`**

Read `edc/core/farming_locations.py` fresh. Find the per-record normalization loop:

```python
                    for rec in arr:
                        if not isinstance(rec, dict):
                            continue
                        # Normalize core fields
                        name = self._norm(rec.get("name")) or "Farm Site"
                        system = self._norm(rec.get("system"))
                        body = self._norm(rec.get("body"))
                        method = self._norm(rec.get("method"))
                        mats = rec.get("key_materials") or rec.get("materials") or rec.get("mats") or []
                        if not isinstance(mats, list):
                            mats = []
                        mats_clean = []
                        for x in mats:
                            s = self._norm(x)
                            if s:
                                mats_clean.append(s)

                        out = dict(rec)
                        out["domain"] = dom
                        out["name"] = name
                        if system:
                            out["system"] = system
                        if body:
                            out["body"] = body
                        if method:
                            out["method"] = method
                        out["key_materials"] = mats_clean

                        records.append(out)
```

Replace with:

```python
                    for rec in arr:
                        if not isinstance(rec, dict):
                            continue
                        # Normalize core fields
                        name = self._norm(rec.get("name")) or "Farm Site"
                        system = self._norm(rec.get("system"))
                        body = self._norm(rec.get("body"))
                        method = self._norm(rec.get("method"))
                        mats = rec.get("key_materials") or rec.get("materials") or rec.get("mats") or []
                        if not isinstance(mats, list):
                            mats = []
                        mats_clean = []
                        for x in mats:
                            s = self._norm(x)
                            if s:
                                mats_clean.append(s)
                        state_tags = rec.get("state_tags") or []
                        if not isinstance(state_tags, list):
                            state_tags = []
                        state_tags_clean = []
                        for x in state_tags:
                            s = self._norm(x).lower()
                            if s:
                                state_tags_clean.append(s)

                        out = dict(rec)
                        out["domain"] = dom
                        out["name"] = name
                        if system:
                            out["system"] = system
                        if body:
                            out["body"] = body
                        if method:
                            out["method"] = method
                        out["key_materials"] = mats_clean
                        if state_tags_clean:
                            out["state_tags"] = state_tags_clean

                        records.append(out)
```

(`out = dict(rec)` already copies the raw `examples` field through unchanged — no separate handling needed for it in this file.)

- [ ] **Step 9: Run the full test file to verify all tests pass**

Run: `pytest tests/test_farming_guide_matching.py -v`
Expected: all tests PASS, including `test_loader_carries_state_tags_through`.

- [ ] **Step 10: Add `state_tags` to the 5 guide entries in `settings/elite_farming_locations.json`**

Read the file fresh first (it's been edited twice already this session — confirm current exact state before editing).

In the `"encoded"` domain, find `"HGE Pharmaceutical Isolators"` and add `"state_tags": ["outbreak"]` to it:

```json
      {
        "name": "HGE Pharmaceutical Isolators",
        "method": "Search high-population Outbreak systems for High Grade Emissions, then collect and trade as needed",
        "key_materials": [
          "Pharmaceutical Isolators"
        ],
        "state_tags": ["outbreak"]
      }
```

In the `"manufactured"` domain, find `"Combat / CZ / bounty cleanup"` and add `"state_tags": ["war", "pirate_attack"]`:

```json
      {
        "name": "Combat / CZ / bounty cleanup",
        "method": "Low/High CZs, RES sites, pirate massacre loops, then scoop salvage",
        "key_materials": [
          "Mixed manufactured materials"
        ],
        "state_tags": ["war", "pirate_attack"]
      }
```

In the `"odyssey_onfoot"` domain, find `"Pirate Attack settlements"` and add `"state_tags": ["pirate_attack", "war", "civil_unrest", "infrastructure_failure"]`:

```json
      {
        "name": "Pirate Attack settlements",
        "method": "Check the Intel tab's Odyssey Farming Candidates card for systems currently tracked in Pirate Attack, Civil Unrest, War, or Infrastructure Failure, then farm settlements there",
        "key_materials": [
          "Broad Odyssey material coverage"
        ],
        "note": "Good category to keep, but the exact best system changes over time.",
        "state_tags": ["pirate_attack", "war", "civil_unrest", "infrastructure_failure"]
      }
```

In the same `"odyssey_onfoot"` domain, find `"Anarchy-government systems"` and add `"state_tags": ["anarchy"]`:

```json
      {
        "name": "Anarchy-government systems",
        "method": "Find a system where the controlling faction's Government is Anarchy; disable settlement alarms once inside, then loot without triggering a bounty or crime consequence",
        "key_materials": [
          "Broad Odyssey material coverage"
        ],
        "note": "No local law means no crime stat penalty for looting or trespassing.",
        "state_tags": ["anarchy"]
      }
```

In the same `"odyssey_onfoot"` domain, find `"Power Generator Reactivation missions"` and add `"state_tags": ["war"]`:

```json
      {
        "name": "Power Generator Reactivation missions",
        "method": "Accept a Power Generator Reactivation mission in a war-state system; it grants level-3 clearance to loot the entire settlement without triggering hostility, even though the settlement is manned",
        "key_materials": [
          "Suit schematics",
          "Power regulators",
          "Chemical, circuit and tech materials"
        ],
        "note": "Needs a Maverick suit with Arc Cutter and Energy Link to get into powered-down buildings. Considered one of the best overall sources for these material categories.",
        "state_tags": ["war"]
      }
```

Do NOT add `state_tags` to `"High Wake Scans"` or to `"High Grade Emissions (HGE)"`. Do NOT touch any other entry.

- [ ] **Step 11: Validate the JSON and confirm the loader still works**

Run: `python -c "import json; json.load(open('settings/elite_farming_locations.json', encoding='utf-8')); print('JSON OK')"`
Expected: `JSON OK`

Run: `python -c "from edc.core.farming_locations import FarmingLocations; fl = FarmingLocations('settings'); print(fl.has_data(), len(fl._records))"`
Expected: `True` and a record count (no exception).

- [ ] **Step 12: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass, including every test added in this task and the full pre-existing suite (no regressions).

- [ ] **Step 13: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/intel_panel.py', encoding='utf-8').read()); ast.parse(open('edc/core/farming_locations.py', encoding='utf-8').read()); print('PARSE OK')"`
Expected: `PARSE OK`

- [ ] **Step 14: Manual live verification**

Start the app. Visit (or re-enter, to force a refresh) a system where you can confirm the live BGS state via the Overview/Intel tabs (e.g. a system in Boom, War, or Outbreak). Confirm:
1. "FARMING LOCATIONS — THIS SYSTEM" no longer shows "High Wake Scans" purely because the system happens to be Anarchy (it should never appear via live match now, only if it's ever given an explicit `system` field).
2. If the current system is in Boom (not Outbreak), "HGE Pharmaceutical Isolators" no longer appears.
3. If the current system's HGE entry live-matches (Boom, War, Outbreak, or Empire/Federation allegiance), the card shows only the specific matched material(s) with their state (e.g. "⚡ Proto Heat Radiators — Boom"), not all 5 examples and not just a generic method line.

- [ ] **Step 15: Commit**

```bash
git add edc/ui/panels/intel_panel.py edc/core/farming_locations.py settings/elite_farming_locations.json tests/test_farming_guide_matching.py
git commit -m "fix: replace keyword-guessed farming-guide matches with curated per-entry tags

Free-text keyword search against each guide entry's name+method text
produced real false positives (HGE Pharmaceutical Isolators wrongly
matching Boom via an 'hge'/'high grade' substring hit; High Wake Scans
wrongly matching Anarchy via a 'wake scan' substring hit) and a false
negative (Pirate Attack settlements couldn't match Civil Unrest or
Infrastructure Failure -- those live tags didn't exist). Matching is
now driven by explicit state_tags curated on each entry, or -- for the
HGE manufactured entry's per-material examples[] list -- derived from
each example's own state text. The Intel tab now shows only the
specific matched material(s), not a generic entry-level pointer."
```
