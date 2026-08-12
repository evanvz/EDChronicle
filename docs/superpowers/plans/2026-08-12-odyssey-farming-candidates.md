# Odyssey Farming Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "ODYSSEY FARMING CANDIDATES" card to the Intel tab that surfaces tracked systems currently safe/good for on-foot settlement material farming (Anarchy government, or War/Civil War/Pirate Attack/Civil Unrest/Infrastructure Failure BGS states), plus enrich the existing static farming guide with settlement-safety tips.

**Architecture:** A pure-data addition to the existing `settings/elite_farming_locations.json` guide (no code change), a new `Repository.get_odyssey_farming_candidates()` query classifying the latest controlling-faction row per system from `faction_snapshots`, and a new card in `IntelPanel` following the exact visual/wiring pattern its four existing cards already use.

**Tech Stack:** Python, PyQt6, SQLite (stdlib `sqlite3` via the project's `Database`/`Repository` wrapper), `pytest`.

## Global Constraints

- "Anarchy" is a **Government** value (`faction_snapshots.government`), not an Allegiance — verified directly against `edc/core/edsm_faction_lookup.py:232-233`, which stores `Government` and `Allegiance` as separate fields. Do not check `allegiance` for this feature.
- State matching must reuse the exact normalization convention already established in `edc/ui/panels/player_faction_panel.py::_parse_states()` (parses the JSON-encoded `active_states` column into a list of `State` strings) and its lowercase-no-space comparison style (e.g. `"civilwar"`, `"pirateattack"`, `"civilunrest"`, `"infrastructurefailure"` — FDev's internal enum strings have no spaces, `.lower()` alone is sufficient normalization). `persistence/repository.py` must not import from `edc/ui/panels/player_faction_panel.py` (persistence layer doesn't depend on UI layer) — duplicate the small parsing helper locally in `repository.py` instead.
- Only rows where `is_controlling = 1` are eligible — the controlling faction determines a system's actual government/law, matching how in-game safety works. Per-system, use only the most recent `snapshot_date` among that system's controlling-faction rows.
- Sort order: freshest `data_timestamp` first (rows with `NULL` `data_timestamp` — pre-freshness-plan legacy rows — sort last, not first). Cap: top 20 results.
- No squadron-faction filter — scan every system in `faction_snapshots` regardless of tracked faction, per the approved design.
- `faction_snapshots` already has a 30-day rolling retention delete (`persistence/repository.py:397-404`, unrelated to this plan, not to be touched) — this bounds how stale any candidate's data can possibly be to begin with.
- New card must match the existing 4 Intel cards' exact visual pattern: `QFrame` with `background`/`border`/`border-radius: 5px` style, a bold 12px letter-spaced `#7a7a7a` header `QLabel`, and a word-wrapped rich-text body `QLabel` with `background: transparent; border: none;`. Use an accent color not already used by the other 4 cards (`#0d1a2a`/`#1e3a5a` POI, `#1a1400`/`#3a2e00` farming, `#0d1a1a`/`#1a3a3a` body-scan, `#0d1a10`/`#1e3a20` guide, `#0d0d1a`/`#2a2a4a` BGS) — use a muted purple frame, e.g. `background: #1a0d1a; border: 1px solid #3a1e3a;`.

---

## File Structure

- **Modify:** `settings/elite_farming_locations.json` — add settlement-safety entries to the `odyssey_onfoot` array and a new key to `bgs_tips`. Pure data, no schema change (the loader already accepts arbitrary per-record fields).
- **Modify:** `persistence/repository.py` — add a module-level `_parse_states()` helper (private to this file, mirrors `player_faction_panel.py`'s) and a new `Repository.get_odyssey_farming_candidates(limit=20)` method.
- **Test:** `tests/test_odyssey_farming_candidates.py` — new file, real temp-file SQLite via the same fixture pattern as `tests/test_faction_snapshot_freshness.py`.
- **Modify:** `edc/ui/panels/intel_panel.py` — add the new card's widgets in `__init__`, add an `_odyssey_candidates_html()` render helper, wire it into `refresh()` via a new optional `farming_candidates=None` parameter.
- **Modify:** `edc/ui/main_window.py` — `_refresh_intel()` (line 3696) fetches `self.repo.get_odyssey_farming_candidates()` and passes it through; the `_clear_all_panels()` call site (line 3871-3873) is left unchanged (already omits `faction_history` too, by design, since it's a cheap system-jump clear, not a real data refresh).

---

### Task 1: Static farming guide content

**Files:**
- Modify: `settings/elite_farming_locations.json`

**Interfaces:**
- Consumes: nothing (pure data file)
- Produces: nothing new consumed by later tasks — this task is independent of Tasks 2/3

- [ ] **Step 1: Add settlement-safety entries to `odyssey_onfoot`**

Open `settings/elite_farming_locations.json`. Inside `"farming_locations"` → `"odyssey_onfoot"` (currently a 4-element array ending with the "Pirate Attack settlements" entry at the closing `]` before `"guardian"`), add these 3 new entries at the end of the array (after the existing "Pirate Attack settlements" entry, before the array's closing `]`):

```json
      {
        "name": "Abandoned settlements",
        "method": "Land at any settlement showing no power/lights and no NPC activity; walk in and loot freely",
        "key_materials": [
          "Broad Odyssey material coverage"
        ],
        "note": "Zero resistance -- no active defenses, no alarms, no NPCs. The single safest category for material farming."
      },
      {
        "name": "Anarchy-government systems",
        "method": "Find a system where the controlling faction's Government is Anarchy; disable settlement alarms once inside, then loot without triggering a bounty or crime consequence",
        "key_materials": [
          "Broad Odyssey material coverage"
        ],
        "note": "No local law means no crime stat penalty for looting or trespassing."
      },
      {
        "name": "Power Generator Reactivation missions",
        "method": "Accept a Power Generator Reactivation mission in a war-state system; it grants level-3 clearance to loot the entire settlement without triggering hostility, even though the settlement is manned",
        "key_materials": [
          "Suit schematics",
          "Power regulators",
          "Chemical, circuit and tech materials"
        ],
        "note": "Needs a Maverick suit with Arc Cutter and Energy Link to get into powered-down buildings. Considered one of the best overall sources for these material categories."
      }
```

- [ ] **Step 2: Add building-type hints to `bgs_tips`**

In the same file, inside `"bgs_tips"` (after the existing `"method"` key, before the closing `}` of `bgs_tips`), add a new key:

```json
    "odyssey_building_types": {
      "EXT": "Extraction settlements -- skew toward Manufactured materials",
      "IND": "Industrial settlements -- skew toward Manufactured materials",
      "STO": "Storage settlements -- skew toward Goods (e.g. ionized gas for weapon upgrades)"
    }
```

- [ ] **Step 3: Validate the JSON is well-formed**

Run: `python -c "import json; json.load(open('settings/elite_farming_locations.json', encoding='utf-8'))"`
Expected: no output, exit code 0 (a `json.JSONDecodeError` means a syntax mistake in Steps 1-2 — fix before continuing).

- [ ] **Step 4: Commit**

```bash
git add settings/elite_farming_locations.json
git commit -m "docs: add settlement-safety tips to Odyssey on-foot farming guide"
```

---

### Task 2: `Repository.get_odyssey_farming_candidates()`

**Files:**
- Modify: `persistence/repository.py`
- Test: `tests/test_odyssey_farming_candidates.py`

**Interfaces:**
- Consumes: `faction_snapshots` table columns `system_address, faction_name, snapshot_date, government, faction_state, active_states, is_controlling, data_timestamp` (all already exist — no migration needed); `systems` table column `system_name`; `Repository.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, data_timestamp, source)` and `Repository.save_system_name_if_missing(system_address, system_name)` (both already exist, used only by this task's tests to build fixtures)
- Produces: `Repository.get_odyssey_farming_candidates(limit: int = 20) -> list[dict]`, each dict shaped `{"system_name": str, "matched_signals": list[str], "data_timestamp": Optional[str]}` — Task 3 consumes this exact shape

- [ ] **Step 1: Write the failing tests**

Create `tests/test_odyssey_farming_candidates.py`:

```python
"""Tests for Repository.get_odyssey_farming_candidates() -- real SQLite
(temp file), not mocks, since the query does the classification logic
that matters here."""
import json

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _save(repo, system_address, system_name, faction_name, government=None,
          faction_state=None, active_states=None, is_controlling=True,
          data_timestamp="2026-08-12T00:00:00Z"):
    repo.save_system_name_if_missing(system_address, system_name)
    faction = {"Name": faction_name, "Influence": 0.5}
    if government is not None:
        faction["Government"] = government
    if faction_state is not None:
        faction["FactionState"] = faction_state
    if active_states is not None:
        faction["ActiveStates"] = active_states
    repo.save_faction_snapshot(
        system_address, faction, "2026-08-12", is_controlling,
        data_timestamp, "journal",
    )


def test_anarchy_government_is_a_candidate(repo):
    _save(repo, 1, "Anarchy System", "Faction A", government="Anarchy")
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert result[0]["system_name"] == "Anarchy System"
    assert "Anarchy" in result[0]["matched_signals"]


def test_democracy_government_is_not_a_candidate(repo):
    _save(repo, 1, "Normal System", "Faction A", government="Democracy")
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_war_faction_state_is_a_candidate(repo):
    _save(repo, 2, "War System", "Faction B", government="Democracy",
          faction_state="War")
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert "War" in result[0]["matched_signals"]


def test_pirate_attack_in_active_states_is_a_candidate(repo):
    _save(repo, 3, "Pirate System", "Faction C", government="Democracy",
          active_states=[{"State": "PirateAttack", "Trend": 0}])
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert "Pirate Attack" in result[0]["matched_signals"]


def test_civil_unrest_and_infrastructure_failure_detected(repo):
    _save(repo, 4, "Unrest System", "Faction D", government="Democracy",
          active_states=[{"State": "CivilUnrest", "Trend": 0}])
    _save(repo, 5, "Infra System", "Faction E", government="Democracy",
          active_states=[{"State": "InfrastructureFailure", "Trend": 0}])
    result = repo.get_odyssey_farming_candidates()
    by_name = {r["system_name"]: r["matched_signals"] for r in result}
    assert "Civil Unrest" in by_name["Unrest System"]
    assert "Infrastructure Failure" in by_name["Infra System"]


def test_multiple_signals_all_reported(repo):
    _save(repo, 6, "Chaos System", "Faction F", government="Anarchy",
          faction_state="War")
    result = repo.get_odyssey_farming_candidates()
    assert set(result[0]["matched_signals"]) == {"Anarchy", "War"}


def test_non_controlling_faction_is_ignored(repo):
    _save(repo, 7, "Uncontrolled System", "Faction G", government="Anarchy",
          is_controlling=False)
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_only_latest_snapshot_date_used(repo):
    # Older row (different snapshot_date) says Anarchy; only the newest
    # row's classification should count. Use save_faction_snapshot twice
    # with different snapshot_date values via direct calls.
    repo.save_system_name_if_missing(8, "Changed System")
    repo.save_faction_snapshot(
        8, {"Name": "Faction H", "Government": "Anarchy"}, "2026-08-10",
        True, "2026-08-10T00:00:00Z", "journal",
    )
    repo.save_faction_snapshot(
        8, {"Name": "Faction H", "Government": "Democracy"}, "2026-08-12",
        True, "2026-08-12T00:00:00Z", "journal",
    )
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_sorted_freshest_data_timestamp_first(repo):
    _save(repo, 9, "Older", "Faction I", government="Anarchy",
          data_timestamp="2026-08-01T00:00:00Z")
    _save(repo, 10, "Newer", "Faction J", government="Anarchy",
          data_timestamp="2026-08-12T00:00:00Z")
    result = repo.get_odyssey_farming_candidates()
    assert [r["system_name"] for r in result] == ["Newer", "Older"]


def test_limit_caps_results(repo):
    for i in range(25):
        _save(repo, 100 + i, f"System {i}", f"Faction {i}",
              government="Anarchy")
    result = repo.get_odyssey_farming_candidates(limit=20)
    assert len(result) == 20


def test_returns_data_timestamp_field(repo):
    _save(repo, 11, "Timestamped", "Faction K", government="Anarchy",
          data_timestamp="2026-08-11T10:00:00Z")
    result = repo.get_odyssey_farming_candidates()
    assert result[0]["data_timestamp"] == "2026-08-11T10:00:00Z"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_odyssey_farming_candidates.py -v`
Expected: every test FAILs with `AttributeError: 'Repository' object has no attribute 'get_odyssey_farming_candidates'`.

- [ ] **Step 3: Implement `_parse_states()` and `get_odyssey_farming_candidates()`**

In `persistence/repository.py`, add a module-level helper directly after the existing `_normalize_data_timestamp()` function (this file already has `import json` at the top — no new import needed):

```python
def _parse_states(raw) -> List[str]:
    """Parses a faction_snapshots active_states/pending_states/recovering_states
    JSON column (a list of {"State": ..., "Trend": ...} dicts) into a flat
    list of State strings. Mirrors player_faction_panel.py's identical
    helper -- duplicated here rather than imported, since persistence must
    not depend on the UI layer."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        str(s.get("State"))
        for s in data
        if isinstance(s, dict) and s.get("State")
    ]
```

Then add the new method to the `Repository` class, placed directly after `get_faction_history()`:

```python
    def get_odyssey_farming_candidates(self, limit: int = 20) -> list[dict]:
        """
        Odyssey on-foot farming candidates: systems whose most recent
        controlling-faction snapshot shows Anarchy government (no local
        law -- safe to loot without a crime/bounty consequence) or a BGS
        state associated with settlement farming opportunities (War/Civil
        War, Pirate Attack, Civil Unrest, Infrastructure Failure).
        Advisory only -- underlying data can be stale, so results are
        ordered freshest data_timestamp first.
        """
        rows = self.db.execute(
            """
            SELECT fs.system_address, s.system_name, fs.government,
                   fs.faction_state, fs.active_states, fs.data_timestamp
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.is_controlling = 1
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.is_controlling = 1
              )
            """
        ).fetchall()

        candidates = []
        for row in rows:
            r = dict(row)
            signals: List[str] = []

            government = (r.get("government") or "").strip().lower()
            if government == "anarchy":
                signals.append("Anarchy")

            active = {s.lower() for s in _parse_states(r.get("active_states"))}
            faction_state = (r.get("faction_state") or "").strip().lower()
            if faction_state:
                active.add(faction_state)

            if active & {"war", "civilwar"}:
                signals.append("War")
            if "pirateattack" in active:
                signals.append("Pirate Attack")
            if "civilunrest" in active:
                signals.append("Civil Unrest")
            if "infrastructurefailure" in active:
                signals.append("Infrastructure Failure")

            if not signals:
                continue

            candidates.append({
                "system_name": r.get("system_name") or "(unknown system)",
                "matched_signals": signals,
                "data_timestamp": r.get("data_timestamp"),
            })

        candidates.sort(key=lambda c: c["data_timestamp"] or "", reverse=True)
        return candidates[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_odyssey_farming_candidates.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests pass (60+ existing tests plus the 11 new ones).

- [ ] **Step 6: Commit**

```bash
git add persistence/repository.py tests/test_odyssey_farming_candidates.py
git commit -m "feat: add Repository.get_odyssey_farming_candidates()"
```

---

### Task 3: Intel panel card + wiring

**Files:**
- Modify: `edc/ui/panels/intel_panel.py`
- Modify: `edc/ui/main_window.py:3696-3704` (`_refresh_intel()`)

**Interfaces:**
- Consumes: `Repository.get_odyssey_farming_candidates()` from Task 2, returning `list[dict]` shaped `{"system_name": str, "matched_signals": list[str], "data_timestamp": Optional[str]}`
- Produces: `IntelPanel.refresh(self, state, farming_locations, faction_history=None, farming_candidates=None)` — new 4th parameter, backward compatible (existing 2-arg and 3-arg call sites keep working since it defaults to `None`)

- [ ] **Step 1: Add the new card's widgets in `IntelPanel.__init__`**

In `edc/ui/panels/intel_panel.py`, after the existing "BGS history card" block (ends at line 171 with `self._content_layout.addWidget(bgs_frame)`), add a new card block:

```python
        # ── Odyssey farming candidates card ─────────────────────────────────
        odyssey_frame = QFrame()
        odyssey_frame.setStyleSheet(
            "QFrame { background: #1a0d1a; border: 1px solid #3a1e3a;"
            "border-radius: 5px; }"
        )
        odyssey_l = QVBoxLayout(odyssey_frame)
        odyssey_l.setContentsMargins(8, 6, 8, 6)
        odyssey_l.setSpacing(4)
        odyssey_hdr = QLabel("ODYSSEY FARMING CANDIDATES")
        odyssey_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        odyssey_l.addWidget(odyssey_hdr)
        self.odyssey_display = QLabel("")
        self.odyssey_display.setWordWrap(True)
        self.odyssey_display.setTextFormat(Qt.TextFormat.RichText)
        self.odyssey_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.odyssey_display.setStyleSheet("background: transparent; border: none;")
        odyssey_l.addWidget(self.odyssey_display)
        self._content_layout.addWidget(odyssey_frame)
```

- [ ] **Step 2: Add a render helper for the candidate rows**

Add this method directly after `_farm_entry_html()` (which ends at line 301 with `return line`):

```python
    def _odyssey_candidates_html(self, candidates):
        """Renders the Odyssey farming candidates list as rich-text rows."""
        if not candidates:
            return (
                '<span style="color:#444444;font-size:12px;">'
                'No tracked systems currently match — data comes from '
                'systems you’ve visited or refreshed.</span>'
            )

        rows = []
        for c in candidates:
            system_name = str(c.get("system_name") or "")
            signals = c.get("matched_signals") or []
            age_txt = self._format_age(c.get("data_timestamp"))

            badges = "".join(
                f'<span style="background:#2a1a2a;color:#C77DFF;'
                f'font-size:12px;font-weight:700;padding:1px 5px;'
                f'border-radius:3px;margin-right:4px;">{self._esc(sig)}</span>'
                for sig in signals
            )
            rows.append(
                '<div style="margin-bottom:6px;">'
                f'<span style="color:#CCCCCC;font-weight:700;">{self._esc(system_name)}</span> '
                f'{badges}'
                + (
                    f'<br><span style="color:#7a7a7a;font-size:12px;">'
                    f'&nbsp;&nbsp;{self._esc(age_txt)}</span>'
                    if age_txt else ""
                )
                + '</div>'
            )
        return "".join(rows)

    def _format_age(self, data_timestamp):
        """Turns a normalized 'YYYY-MM-DDTHH:MM:SSZ' timestamp into a short
        human-readable age string, e.g. 'today', '3 days ago'. Returns ''
        for missing/unparseable input (legacy rows with no timestamp)."""
        if not data_timestamp:
            return ""
        from datetime import datetime, timezone
        try:
            dt = datetime.strptime(data_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return ""
        days = (datetime.now(timezone.utc) - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "1 day ago"
        return f"{days} days ago"
```

- [ ] **Step 3: Wire the new parameter into `refresh()`**

In `edc/ui/panels/intel_panel.py`, change the `refresh()` signature (currently `def refresh(self, state, farming_locations, faction_history=None):`) to:

```python
    def refresh(self, state, farming_locations, faction_history=None, farming_candidates=None):
```

Then, inside `refresh()`, directly after the existing "── BGS history ──" block finishes (right after the `self.bgs_display.setText(...)` call), add:

```python
        # ── Odyssey farming candidates ───────────────────────────────────
        self.odyssey_display.setText(
            self._odyssey_candidates_html(farming_candidates or [])
        )
```

- [ ] **Step 4: Wire the repository call in `main_window.py`**

In `edc/ui/main_window.py`, re-read the current `_refresh_intel()` method (around line 3696) fresh before editing -- this file is flagged frequently-stale in this project's CLAUDE.md. Change:

```python
    def _refresh_intel(self):
        system_address = getattr(self.state, "system_address", None)
        faction_history = []
        if isinstance(system_address, int):
            try:
                faction_history = self.repo.get_faction_history(system_address)
            except Exception:
                log.exception("Failed to load faction history")
        self.intel_panel.refresh(self.state, self.farming_locations, faction_history)
```

to:

```python
    def _refresh_intel(self):
        system_address = getattr(self.state, "system_address", None)
        faction_history = []
        if isinstance(system_address, int):
            try:
                faction_history = self.repo.get_faction_history(system_address)
            except Exception:
                log.exception("Failed to load faction history")
        try:
            farming_candidates = self.repo.get_odyssey_farming_candidates()
        except Exception:
            log.exception("Failed to load Odyssey farming candidates")
            farming_candidates = []
        self.intel_panel.refresh(
            self.state, self.farming_locations, faction_history, farming_candidates
        )
```

Leave the other call site (`_clear_all_panels()`, around line 3871-3873) unchanged — it already omits `faction_history` for the same reason (cheap system-jump clear, not a real data refresh), so it will correctly default `farming_candidates` to `None` too.

- [ ] **Step 5: Byte-compile check**

Run: `python -m py_compile edc/ui/panels/intel_panel.py edc/ui/main_window.py`
Expected: no output, exit code 0.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests still pass (this task adds no new automated tests -- UI wiring is verified visually per this project's convention, matching how the other 4 Intel cards were verified).

- [ ] **Step 7: Visual verification**

Launch the app, open the Intel tab, confirm:
- The new "ODYSSEY FARMING CANDIDATES" card renders below the "BGS HISTORY — THIS SYSTEM" card with the muted-purple frame style.
- With no matching systems tracked yet, it shows the empty-state message.
- If any tracked system has Anarchy government or a matching BGS state (check via the Player Faction tab's own bucket tiles for a quick cross-reference, e.g. an existing "Pirate Attack" or "Civil Unrest" tile system), that system appears here with the correct signal badge(s) and a plausible age string.

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/intel_panel.py edc/ui/main_window.py
git commit -m "feat: add Odyssey Farming Candidates card to Intel tab"
```
