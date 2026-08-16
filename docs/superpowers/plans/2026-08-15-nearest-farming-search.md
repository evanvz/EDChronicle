# Nearest Farming Opportunity Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "NEAREST FARMING OPPORTUNITIES" search card to the Intel tab — from the player's current position, find the closest known farming material (static named sites AND live BGS-state-driven opportunities like HGE, sorted nearest-first, optionally filtered by material name).

**Architecture:** A new `Repository` method does a pure data fetch (controlling faction's live BGS state per system, joined to coordinates) — no guide-matching logic, per this codebase's persistence/UI layering rule. A new pure module-level function in `intel_panel.py` derives live tags from a DB row (paralleling the existing `_get_system_opportunities`) and reuses the existing `_entry_matches_system`/`_with_matched_examples` matching functions unchanged. A second pure function merges static-site and live-match results, filters by material, sorts by distance, and caps the result count. `IntelPanel` gains a `repo` reference (following `MiningPanel`'s existing precedent for panels needing interactive DB search) and a new `QTableWidget` card.

**Tech Stack:** Python 3, SQLite3, PyQt6, pytest.

## Global Constraints

- Do not modify `_get_system_opportunities`, `_entry_matches_system`, `_state_text_to_tags`, or `_with_matched_examples` — reuse them exactly as they exist.
- Do not touch the current-system live card's matching (still any-faction, unchanged) — this new search is a deliberately separate, tighter (`is_controlling`-only) code path.
- No distance cutoff/radius setting — sort nearest-first, no filtering by distance. A display cap of 50 results is a UI-sanity limit, not a distance cutoff.
- No voice announcement — not part of this feature.
- `persistence/repository.py` must contain zero guide-matching logic — it only fetches rows. Matching/filtering/sorting logic lives in `edc/ui/panels/intel_panel.py`.

---

### Task 1: Backend — data fetch, tag derivation, and result-building logic

**Files:**
- Modify: `persistence/repository.py`
- Modify: `edc/ui/panels/intel_panel.py`
- Test: `tests/test_nearby_farming_search.py` (new)

**Interfaces:**
- Consumes: existing `_get_system_opportunities`, `_entry_matches_system`, `_with_matched_examples` (all in `edc/ui/panels/intel_panel.py`, unchanged), existing `Repository.get_system_coords_for_names(names: list[str]) -> dict` (unchanged), module-level `_parse_states(raw) -> List[str]` in `persistence/repository.py` (unchanged).
- Produces: `Repository.get_controlling_faction_snapshots_with_coords(self) -> list[dict]`, `_tags_from_faction_snapshot_row(row: dict) -> set` and `_build_nearby_farming_results(static_sites, coords_by_system, live_rows, guide_records, material_filter, ref_x, ref_y, ref_z, limit=50) -> list[dict]` (both module-level in `edc/ui/panels/intel_panel.py`) — consumed by Task 2's `_search_nearby_farming` orchestration method.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_farming_guide_matching.py` and `tests/test_fleet_carrier_materials.py` in full first, to confirm the current exact `repo`/`tmp_path` fixture pattern this repo uses. Create `tests/test_nearby_farming_search.py`:

```python
"""Tests for the nearest-farming-opportunity search: the repository's
raw data fetch, the pure tag-derivation function, and the pure
merge/filter/sort function. No Qt/QApplication needed for the pure
functions (matches tests/test_farming_guide_matching.py's pattern)."""
import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.ui.panels.intel_panel import (
    _tags_from_faction_snapshot_row,
    _build_nearby_farming_results,
)


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_system(repo, system_address, system_name, x, y, z):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_snapshot(
    repo, system_address, faction_name="Test Faction", government="Democracy",
    allegiance="Independent", faction_state="None", active_states=None,
    is_controlling=True, snapshot_date="2026-08-15",
):
    faction = {
        "Name": faction_name,
        "Government": government,
        "Allegiance": allegiance,
        "FactionState": faction_state,
    }
    if active_states is not None:
        faction["ActiveStates"] = active_states
    repo.save_faction_snapshot(
        system_address, faction, snapshot_date, is_controlling, snapshot_date, "edsm"
    )


# --- Repository.get_controlling_faction_snapshots_with_coords ---

def test_returns_controlling_faction_with_coords(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert len(rows) == 1
    assert rows[0]["system_name"] == "Sol"
    assert rows[0]["faction_state"] == "Boom"
    assert rows[0]["x"] == 0.0


def test_excludes_non_controlling_faction(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_name="Minor Faction", faction_state="Boom", is_controlling=False)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert rows == []


def test_only_most_recent_snapshot_date_returned(repo):
    _seed_system(repo, 1, "Sol", 0.0, 0.0, 0.0)
    _seed_snapshot(repo, 1, faction_state="War", is_controlling=True, snapshot_date="2026-08-10")
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True, snapshot_date="2026-08-15")

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert len(rows) == 1
    assert rows[0]["faction_state"] == "Boom"


def test_excludes_system_with_no_coords(repo):
    # No _seed_system coords call -- system_address 1 has a snapshot but
    # no system_coords row, so distance can't be computed.
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (1, "Sol"),
    )
    _seed_snapshot(repo, 1, faction_state="Boom", is_controlling=True)

    rows = repo.get_controlling_faction_snapshots_with_coords()
    assert rows == []


# --- _tags_from_faction_snapshot_row ---

def test_tags_from_row_anarchy():
    row = {"government": "Anarchy", "allegiance": "Independent", "faction_state": "None", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"anarchy"}


def test_tags_from_row_empire_allegiance():
    row = {"government": "Patronage", "allegiance": "Empire", "faction_state": "None", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"empire"}


def test_tags_from_row_boom_faction_state():
    row = {"government": "Democracy", "allegiance": "Independent", "faction_state": "Boom", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == {"boom"}


def test_tags_from_row_civil_unrest_active_state():
    row = {
        "government": "Democracy", "allegiance": "Independent", "faction_state": "None",
        "active_states": '[{"State": "CivilUnrest", "Trend": 0}]',
    }
    assert _tags_from_faction_snapshot_row(row) == {"civil_unrest"}


def test_tags_from_row_empty_produces_no_tags():
    row = {"government": "", "allegiance": "", "faction_state": "", "active_states": None}
    assert _tags_from_faction_snapshot_row(row) == set()


# --- _build_nearby_farming_results ---

_STATIC_SITE = {
    "name": "Arai's Mine",
    "system": "Iah Bulu",
    "domain": "odyssey_onfoot",
    "key_materials": ["Broad Odyssey material coverage"],
}

_HGE_ENTRY = {
    "name": "High Grade Emissions (HGE)",
    "domain": "manufactured",
    "examples": [
        {"material": "Pharmaceutical Isolators", "state": "Outbreak"},
        {"material": "Proto Heat Radiators", "state": "Boom"},
    ],
}


def test_static_site_produces_result_with_correct_distance():
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[],
        guide_records=[],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Broad Odyssey material coverage"
    assert results[0]["system_name"] == "Iah Bulu"
    assert results[0]["distance_ly"] == 50.0
    assert results[0]["source"] == "static"
    assert results[0]["state"] is None


def test_live_match_produces_result_with_state():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "Boom", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Proto Heat Radiators"
    assert results[0]["system_name"] == "Sol"
    assert results[0]["distance_ly"] == 10.0
    assert results[0]["source"] == "live"
    assert results[0]["state"] == "Boom"


def test_material_filter_narrows_both_sources():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "Boom", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],
        material_filter="proto heat",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 1
    assert results[0]["material"] == "Proto Heat Radiators"


def test_results_sorted_nearest_first_across_both_sources():
    near_live_row = {
        "system_name": "Near", "government": "Anarchy", "allegiance": "Independent",
        "faction_state": "None", "active_states": None, "x": 5.0, "y": 0.0, "z": 0.0,
    }
    anarchy_entry = {"name": "Anarchy-government systems", "domain": "odyssey_onfoot",
                      "state_tags": ["anarchy"], "key_materials": ["Broad Odyssey material coverage"]}
    results = _build_nearby_farming_results(
        static_sites=[_STATIC_SITE],  # Iah Bulu at distance 50.0
        coords_by_system={"iah bulu": (30.0, 40.0, 0.0)},
        live_rows=[near_live_row],  # distance 5.0
        guide_records=[anarchy_entry],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert len(results) == 2
    assert results[0]["system_name"] == "Near"
    assert results[1]["system_name"] == "Iah Bulu"


def test_display_cap_respected():
    live_rows = [
        {
            "system_name": f"System {i}", "government": "Anarchy", "allegiance": "Independent",
            "faction_state": "None", "active_states": None, "x": float(i), "y": 0.0, "z": 0.0,
        }
        for i in range(60)
    ]
    anarchy_entry = {"name": "Anarchy-government systems", "domain": "odyssey_onfoot",
                      "state_tags": ["anarchy"], "key_materials": ["Broad Odyssey material coverage"]}
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=live_rows,
        guide_records=[anarchy_entry],
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
        limit=50,
    )
    assert len(results) == 50


def test_unmatched_guide_record_produces_nothing():
    live_row = {
        "system_name": "Sol", "government": "Democracy", "allegiance": "Independent",
        "faction_state": "None", "active_states": None, "x": 0.0, "y": 0.0, "z": 10.0,
    }
    results = _build_nearby_farming_results(
        static_sites=[],
        coords_by_system={},
        live_rows=[live_row],
        guide_records=[_HGE_ENTRY],  # needs outbreak/boom/war/empire/federation, none present
        material_filter="",
        ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_nearby_farming_search.py -v`
Expected: FAIL — `ImportError` on `_tags_from_faction_snapshot_row`/`_build_nearby_farming_results` (don't exist yet), plus `AttributeError` on `get_controlling_faction_snapshots_with_coords` once the import is fixed to test in isolation.

- [ ] **Step 3: Add `Repository.get_controlling_faction_snapshots_with_coords`**

Read `persistence/repository.py` fresh, find `get_odyssey_farming_candidates` (search for that exact method name — it's the reference JOIN shape), and add a new method directly after it:

```python
    def get_controlling_faction_snapshots_with_coords(self) -> list[dict]:
        """
        Every system's controlling faction's most recent snapshot, joined
        to its known coordinates -- raw data only, no guide-matching logic
        (that belongs in the UI layer -- see _parse_states()'s docstring
        for why persistence must not depend on it). Systems with no
        system_coords row are excluded, since distance can't be computed
        without one.
        """
        rows = self.db.execute(
            """
            SELECT s.system_name, fs.government, fs.allegiance,
                   fs.faction_state, fs.active_states,
                   sc.x, sc.y, sc.z
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            INNER JOIN system_coords sc ON sc.system_name = s.system_name
            WHERE fs.is_controlling = 1
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.is_controlling = 1
              )
            """
        ).fetchall()
        return [dict(r) for r in rows]
```

(Confirm `self.db.execute` is the correct call form by checking how `get_odyssey_farming_candidates` itself issues its query in the current file — match that exact style, whether `self.db.execute(...)` or `self.db.conn.execute(...)`.)

- [ ] **Step 4: Add `_tags_from_faction_snapshot_row` to `intel_panel.py`**

Read `edc/ui/panels/intel_panel.py` fresh, find `_get_system_opportunities` (the module-level function near the top of the file), and add a new top-level import plus a new function directly after it.

Add to the import block at the top of the file:

```python
from persistence.repository import _parse_states
```

Add directly after `_get_system_opportunities`'s closing `return tags` line, before `_STATE_TEXT_TAGS`:

```python
def _tags_from_faction_snapshot_row(row: dict) -> set:
    """
    Same tag vocabulary as _get_system_opportunities(), derived from a
    persisted faction_snapshots row (government/allegiance/faction_state/
    active_states) instead of live game state -- used for searching
    systems the player isn't currently in. No security/economy tags:
    faction_snapshots doesn't carry those columns (they're system-level,
    not per-faction), and none of this guide's state_tags need them.
    """
    tags = set()
    govt = str(row.get("government") or "").lower()
    alleg = str(row.get("allegiance") or "").lower()
    if "anarchy" in govt:
        tags.add("anarchy")
    if "empire" in alleg:
        tags.add("empire")
    if "federation" in alleg:
        tags.add("federation")

    all_states = [str(row.get("faction_state") or "").lower()]
    all_states += [s.lower() for s in _parse_states(row.get("active_states"))]
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

- [ ] **Step 5: Run the repository and tag-derivation tests to verify they pass**

Run: `pytest tests/test_nearby_farming_search.py -v -k "controlling_faction or tags_from_row"`
Expected: those tests PASS. The `_build_nearby_farming_results` tests still FAIL (not implemented yet).

- [ ] **Step 6: Add `_build_nearby_farming_results` to `intel_panel.py`**

Find `_with_matched_examples` (added in an earlier commit this session) and add this new function directly after it:

```python
def _build_nearby_farming_results(
    static_sites: list,
    coords_by_system: dict,
    live_rows: list,
    guide_records: list,
    material_filter: str,
    ref_x: float, ref_y: float, ref_z: float,
    limit: int = 50,
) -> list:
    """
    Combines static named-site matches and live BGS-state matches into
    one nearest-first, optionally material-filtered result list.

    static_sites: guide records with a "system" field.
    coords_by_system: {system_name_lower: (x, y, z)} for static_sites'
    systems.
    live_rows: raw rows from Repository.get_controlling_faction_snapshots_with_coords().
    guide_records: the full farming_locations._records list, matched
    against each live_row's derived tags.
    """
    def _dist(x, y, z):
        return ((x - ref_x) ** 2 + (y - ref_y) ** 2 + (z - ref_z) ** 2) ** 0.5

    mf = (material_filter or "").strip().lower()
    results = []

    for site in static_sites:
        sys_name = str(site.get("system") or "")
        coords = coords_by_system.get(sys_name.lower())
        if not coords:
            continue
        x, y, z = coords
        dist = _dist(x, y, z)
        materials = site.get("key_materials") or []
        examples = site.get("examples") or []
        mat_names = list(materials) if materials else [
            str(ex.get("material") or "") for ex in examples if isinstance(ex, dict)
        ]
        for mat in mat_names:
            if not mat:
                continue
            if mf and mf not in mat.lower():
                continue
            results.append({
                "material": mat,
                "site_name": str(site.get("name") or ""),
                "system_name": sys_name,
                "distance_ly": dist,
                "source": "static",
                "state": None,
            })

    for row in live_rows:
        x, y, z = row.get("x"), row.get("y"), row.get("z")
        if x is None or y is None or z is None:
            continue
        dist = _dist(x, y, z)
        tags = _tags_from_faction_snapshot_row(row)
        if not tags:
            continue
        for rec in guide_records:
            if not isinstance(rec, dict):
                continue
            matched_tags = _entry_matches_system(rec, tags)
            if not matched_tags:
                continue
            entry = _with_matched_examples(rec, matched_tags, tags)
            matched_examples = entry.get("_matched_examples")
            if matched_examples:
                mat_state_pairs = [
                    (str(ex.get("material") or ""), str(ex.get("state") or ""))
                    for ex in matched_examples
                ]
            else:
                mat_state_pairs = [
                    (mat, None) for mat in (rec.get("key_materials") or [])
                ]
            for mat, st in mat_state_pairs:
                if not mat:
                    continue
                if mf and mf not in mat.lower():
                    continue
                results.append({
                    "material": mat,
                    "site_name": str(rec.get("name") or ""),
                    "system_name": str(row.get("system_name") or ""),
                    "distance_ly": dist,
                    "source": "live",
                    "state": st,
                })

    results.sort(key=lambda r: r["distance_ly"])
    return results[:limit]
```

- [ ] **Step 7: Run the full new test file to verify all tests pass**

Run: `pytest tests/test_nearby_farming_search.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests pass (this touches shared repository/intel_panel code — confirm nothing else broke).

- [ ] **Step 9: Static syntax check**

Run: `python -c "import ast; ast.parse(open('persistence/repository.py', encoding='utf-8').read()); ast.parse(open('edc/ui/panels/intel_panel.py', encoding='utf-8').read()); print('PARSE OK')"`
Expected: `PARSE OK`

- [ ] **Step 10: Commit**

```bash
git add persistence/repository.py edc/ui/panels/intel_panel.py tests/test_nearby_farming_search.py
git commit -m "feat: add backend logic for nearest farming opportunity search

New Repository.get_controlling_faction_snapshots_with_coords() does a
pure data fetch (no guide-matching logic, per this codebase's
persistence/UI layering rule). Two new pure functions in
intel_panel.py -- _tags_from_faction_snapshot_row() (parallels
_get_system_opportunities() for stored data instead of live state) and
_build_nearby_farming_results() (merges static named-site matches and
live BGS-state matches, filters by material, sorts nearest-first) --
reuse the existing _entry_matches_system()/_with_matched_examples()
matching logic unchanged."
```

---

### Task 2: UI — search card, filter box, results table, click-to-copy

**Files:**
- Modify: `edc/ui/panels/intel_panel.py`
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `Repository.get_controlling_faction_snapshots_with_coords()`, `Repository.get_system_coords_for_names(names)`, `_build_nearby_farming_results(...)` — all from Task 1, unchanged.
- Produces: `IntelPanel.__init__(self, repo, parent=None)` (new required `repo` param), `IntelPanel._search_nearby_farming(self, material_filter: str) -> list` — no other task depends on these.

- [ ] **Step 1: Add new imports to `intel_panel.py`**

Read the file's current import block fresh. Add `QLineEdit`, `QTableWidget`, `QTableWidgetItem`, `QHeaderView` to the `PyQt6.QtWidgets` import list (alongside the existing `QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QApplication`).

- [ ] **Step 2: Add `repo` to `IntelPanel.__init__`, store state/farming_locations references**

Read the current `__init__` and `refresh` signatures fresh (`__init__(self, parent=None):`, `refresh(self, state, farming_locations, faction_history=None, farming_candidates=None):`).

Change `__init__(self, parent=None):` to:

```python
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._state = None
        self._farming_locations = None
```

(Place these three new lines immediately after `super().__init__(parent)`, before the existing `outer = QVBoxLayout(self)` line.)

At the top of `refresh()` (the very first lines inside the method body, before any existing logic), add:

```python
        self._state = state
        self._farming_locations = farming_locations
```

- [ ] **Step 3: Add the new card's widgets in `__init__`**

Find the existing `# ── Full farming guide card ──` block and its closing `self._content_layout.addWidget(guide_frame)` line. Insert this new block directly after it, before the `# ── BGS history card ──` comment:

```python
        # ── Nearest farming opportunities card ──────────────────────────────
        nearby_frame = QFrame()
        nearby_frame.setStyleSheet(
            "QFrame { background: #1a1a0d; border: 1px solid #3a3a1e;"
            "border-radius: 5px; }"
        )
        nearby_l = QVBoxLayout(nearby_frame)
        nearby_l.setContentsMargins(8, 6, 8, 6)
        nearby_l.setSpacing(4)
        nearby_hdr = QLabel("NEAREST FARMING OPPORTUNITIES")
        nearby_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        nearby_l.addWidget(nearby_hdr)

        self.nearby_farming_filter = QLineEdit()
        self.nearby_farming_filter.setPlaceholderText("Filter by material...")
        self.nearby_farming_filter.textChanged.connect(self._on_nearby_farming_filter_changed)
        nearby_l.addWidget(self.nearby_farming_filter)

        self.nearby_farming_table = QTableWidget()
        self.nearby_farming_table.setColumnCount(4)
        self.nearby_farming_table.setHorizontalHeaderLabels(
            ["Material", "Site / System", "Distance (ly)", "Source"]
        )
        self.nearby_farming_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.nearby_farming_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.nearby_farming_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.nearby_farming_table.verticalHeader().setVisible(False)
        self.nearby_farming_table.setAlternatingRowColors(True)
        self.nearby_farming_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self.nearby_farming_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.nearby_farming_table.setToolTip("Click the Site / System cell to copy its name to the clipboard.")
        self.nearby_farming_table.cellClicked.connect(self._on_nearby_farming_cell_clicked)
        self.nearby_farming_table.setMinimumHeight(150)
        nearby_l.addWidget(self.nearby_farming_table)

        self._content_layout.addWidget(nearby_frame)
```

- [ ] **Step 4: Add `_search_nearby_farming`, `_on_nearby_farming_filter_changed`, `_on_nearby_farming_cell_clicked` methods**

Add these three new methods to `IntelPanel` — place them near `refresh()` (directly before or after it, matching this file's existing method ordering convention once you've re-read the file):

```python
    def _search_nearby_farming(self, material_filter: str) -> list:
        if not self._farming_locations or self._repo is None:
            return []
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        if ref_x is None or ref_y is None or ref_z is None:
            return []

        all_records = getattr(self._farming_locations, "_records", []) or []
        static_sites = [r for r in all_records if isinstance(r, dict) and r.get("system")]
        static_names = [str(r.get("system")) for r in static_sites]
        coords_raw = self._repo.get_system_coords_for_names(static_names) if static_names else {}
        coords_by_system = {name.lower(): coords for name, coords in coords_raw.items()}

        live_rows = self._repo.get_controlling_faction_snapshots_with_coords()

        return _build_nearby_farming_results(
            static_sites, coords_by_system, live_rows, all_records,
            material_filter, ref_x, ref_y, ref_z,
        )

    def _on_nearby_farming_filter_changed(self):
        results = self._search_nearby_farming(self.nearby_farming_filter.text())
        self.nearby_farming_table.setSortingEnabled(False)
        self.nearby_farming_table.setRowCount(len(results))
        for row, r in enumerate(results):
            self.nearby_farming_table.setItem(row, 0, QTableWidgetItem(r["material"]))
            self.nearby_farming_table.setItem(row, 1, QTableWidgetItem(r["system_name"]))
            self.nearby_farming_table.setItem(row, 2, QTableWidgetItem(f"{r['distance_ly']:.1f}"))
            source_txt = f"Live — {r['state']}" if r.get("state") else ("Live" if r["source"] == "live" else "Static")
            self.nearby_farming_table.setItem(row, 3, QTableWidgetItem(source_txt))

    def _on_nearby_farming_cell_clicked(self, row: int, column: int) -> None:
        if column != 1:  # Site / System
            return
        item = self.nearby_farming_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
```

- [ ] **Step 5: Trigger a refresh of the new card at the end of `refresh()`**

Read `refresh()`'s current end fresh (after the existing `# ── Summary ──` block's `self.intel_summary.setText(...)` call). Add one line at the very end of the method:

```python
        self._on_nearby_farming_filter_changed()
```

- [ ] **Step 6: Update `IntelPanel` instantiation in `main_window.py`**

Read `edc/ui/main_window.py` fresh around the `self.intel_panel = IntelPanel()` line (confirm `self.repo` is already constructed earlier in `__init__`, which it is). Change:

```python
        self.intel_panel = IntelPanel()
```

to:

```python
        self.intel_panel = IntelPanel(self.repo)
```

No other `main_window.py` changes are needed — both existing `self.intel_panel.refresh(...)` call sites already pass `farming_locations` as one of their arguments.

- [ ] **Step 7: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/intel_panel.py', encoding='utf-8').read()); ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read()); print('PARSE OK')"`
Expected: `PARSE OK`

- [ ] **Step 8: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (no regressions from the constructor signature change).

- [ ] **Step 9: Manual live verification**

Start the app. Open the Intel tab. Confirm:
1. A new "NEAREST FARMING OPPORTUNITIES" card appears after "FARMING GUIDE — ALL CATEGORIES", with a filter box and a results table.
2. With the filter box empty, the table shows results (static sites and/or live BGS-state matches), sorted nearest-first (check the Distance column is ascending).
3. Typing a material name (e.g. part of "Broad Odyssey material coverage" or a known HGE material) narrows the table to matching rows only.
4. A live-state result's Source column shows the matched state (e.g. "Live — Boom"); a static site's Source column shows "Static".
5. Clicking the Site/System column copies that system's name to the clipboard (paste somewhere to confirm).
6. Jump to a different system in-game (or wait for a refresh) and confirm the table repopulates without needing to touch the filter box.

- [ ] **Step 10: Commit**

```bash
git add edc/ui/panels/intel_panel.py edc/ui/main_window.py
git commit -m "feat: add NEAREST FARMING OPPORTUNITIES search card to Intel tab

New QTableWidget card, filter-as-you-type by material name, combining
static named-site guide entries and live BGS-state-driven matches
(including HGE), sorted nearest-first with no distance cutoff.
IntelPanel now takes a repo reference (mirroring MiningPanel's
existing precedent for panels needing interactive DB search) for the
first time -- every other card on this panel stays passively fed via
refresh()."
```
