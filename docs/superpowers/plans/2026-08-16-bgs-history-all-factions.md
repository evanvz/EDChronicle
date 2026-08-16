# BGS History Drill-Down (All Factions + Forecast + Graph) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden the existing per-system BGS history drill-down dialog (Player Faction tab, opened from a bucket row's Influence cell) from showing one tracked faction to showing every faction present in that system, with a per-faction forecast line and a multi-line influence-over-time graph — then remove the now-redundant, simpler "BGS HISTORY — THIS SYSTEM" card on the Intel tab.

**Architecture:** Backend: extract the existing single-faction prediction computation into a reusable helper, add a new repository method that runs it for every faction in a system. UI: rebuild the existing `_FactionHistoryDialog` into three stacked sections (forecast pane, `PyQt6.QtCharts` graph, widened table) using a new per-faction color palette for visual linking. Cleanup: delete the Intel tab's now-redundant card and its plumbing.

**Tech Stack:** Python, PyQt6, `PyQt6.QtCharts` (new dependency), SQLite (via existing `Repository`/`Database` wrapper), pytest with a real temp-file SQLite fixture (existing pattern, no mocks).

## Global Constraints

- No schema change — `faction_snapshots` and its 30-day retention prune already support everything this plan needs.
- `Repository.get_faction_predictions(faction_name)`'s existing signature and each returned dict's fields/values must not change — only its internals are refactored.
- New dependency: `PyQt6-Charts==6.10.0` in `requirements.txt` (same minor line as the pinned `PyQt6==6.10.2`).
- Faction **identity** colors (which line/name is which faction — cycled from a fixed 8-color palette) are a different concept from `_format_forecast()`'s **semantic** colors (red=war/retreat, amber=conflict, green=expansion, grey=flat/no-data) — never conflate the two.
- Spec of record: `docs/superpowers/specs/2026-08-16-bgs-history-all-factions-design.md`.

---

### Task 1: Backend — per-faction prediction helper + all-factions-in-system method

**Files:**
- Modify: `persistence/repository.py:523-678` (`get_faction_predictions`)
- Test: `tests/test_faction_predictions_all_factions.py` (new)

**Interfaces:**
- Produces: `Repository._predict_faction_in_system(self, system_address: int, faction_name: str) -> dict` — returns `{"influence": float|None, "trend": "up"|"down"|"flat"|None, "days_in_expansion_range": int|None, "days_in_retreat_range": int|None, "conflict_risk": dict|None, "active_war": dict|None}` (no `system_address`/`system_name` keys — the caller adds those if it needs them).
- Produces: `Repository.get_all_faction_predictions_for_system(self, system_address: int) -> list[dict]` — each entry is `_predict_faction_in_system()`'s dict plus `"faction_name": str`, sorted by `influence` descending (entries with `influence is None` sorted last, relative order among themselves stable/undefined).
- Consumes: nothing new — uses the existing `faction_snapshots` table and the existing module-level `_row_is_at_war()` helper already in this file (used unchanged by the extracted body).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faction_predictions_all_factions.py`:

```python
"""Tests for Repository._predict_faction_in_system() and
get_all_faction_predictions_for_system() -- real SQLite (temp file), no
mocks, matching this repo's established pattern (see
tests/test_active_war_opponent.py)."""
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


def _faction(name, influence, faction_state=None, active_states=None):
    f = {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}
    if faction_state is not None:
        f["FactionState"] = faction_state
    if active_states is not None:
        f["ActiveStates"] = active_states
    return f


def _save(repo, system_address, faction, snapshot_date="2026-08-13", is_controlling=True):
    repo.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, snapshot_date, "edsm")


# --- get_faction_predictions() must still work identically after the extraction ---

def test_get_faction_predictions_unchanged_after_refactor(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert len(predictions) == 1
    assert predictions[0]["system_address"] == 1
    assert predictions[0]["influence"] == 0.6
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


# --- _predict_faction_in_system() ---

def test_predict_faction_in_system_matches_single_faction_shape(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    result = repo._predict_faction_in_system(1, "Our Faction")
    assert result["influence"] == 0.6
    assert result["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}
    assert "system_address" not in result
    assert "system_name" not in result


def test_predict_faction_in_system_no_history_returns_none_fields(repo):
    result = repo._predict_faction_in_system(999, "Nobody Here")
    assert result["influence"] is None
    assert result["trend"] is None
    assert result["days_in_expansion_range"] is None
    assert result["days_in_retreat_range"] is None
    assert result["conflict_risk"] is None
    assert result["active_war"] is None


# --- get_all_faction_predictions_for_system() ---

def test_all_factions_in_system_returns_every_faction(repo):
    _save(repo, 1, _faction("Faction A", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Faction B", 0.2, faction_state="War"))
    _save(repo, 1, _faction("Faction C", 0.1))
    predictions = repo.get_all_faction_predictions_for_system(1)
    names = {p["faction_name"] for p in predictions}
    assert names == {"Faction A", "Faction B", "Faction C"}


def test_all_factions_sorted_by_influence_descending(repo):
    _save(repo, 1, _faction("Low", 0.1))
    _save(repo, 1, _faction("High", 0.7))
    _save(repo, 1, _faction("Mid", 0.4))
    predictions = repo.get_all_faction_predictions_for_system(1)
    assert [p["faction_name"] for p in predictions] == ["High", "Mid", "Low"]


def test_all_factions_none_influence_sorted_last(repo):
    # Faction only ever seen with influence=None (e.g. malformed snapshot)
    # must not crash the sort and must land after every known-influence entry.
    _save(repo, 1, _faction("Known", 0.5))
    _save(repo, 2, _faction("Unrelated System Faction", 0.3))  # different system, must not appear
    repo.db.execute(
        """
        INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date, influence, is_controlling)
        VALUES (1, 'Unknown Influence', '2026-08-13', NULL, 0)
        """
    )
    predictions = repo.get_all_faction_predictions_for_system(1)
    names = [p["faction_name"] for p in predictions]
    assert names == ["Known", "Unknown Influence"]


def test_all_factions_reflects_per_faction_forecast_independently(repo):
    _save(repo, 1, _faction("Expanding Faction", 0.75))
    _save(repo, 1, _faction("Retreating Faction", 0.02))
    predictions = repo.get_all_faction_predictions_for_system(1)
    by_name = {p["faction_name"]: p for p in predictions}
    assert by_name["Expanding Faction"]["days_in_expansion_range"] == 0
    assert by_name["Retreating Faction"]["days_in_retreat_range"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_faction_predictions_all_factions.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute '_predict_faction_in_system'` (and `get_all_faction_predictions_for_system`).

- [ ] **Step 3: Extract `_predict_faction_in_system` and add `get_all_faction_predictions_for_system`**

In `persistence/repository.py`, replace the current `get_faction_predictions` method (lines 523-678) with:

```python
    def get_faction_predictions(self, faction_name: str) -> List[dict]:
        """
        BGS expansion/retreat/conflict prediction, per tracked system, built
        entirely from faction_snapshots history already being collected —
        no new data source. Thresholds are the real Elite Dangerous BGS
        mechanics (not guessed): expansion triggers at >=75% influence,
        retreat triggers below 2.5% (with a 5-6 day grace window), and a
        conflict (War/CivilWar/Election) triggers when two factions'
        influence converges within a few points, both above a 7% floor.

        Each entry:
          system_address, system_name, influence, trend ("up"/"down"/"flat"/None),
          days_in_expansion_range (int or None), days_in_retreat_range (int or None),
          conflict_risk (None or {"faction_name", "influence", "diff"}),
          active_war (None, or {"faction_name", "influence"} where
          faction_name/influence are None if no opponent could be
          identified)

        trend/day-counts are None when there isn't enough history yet (a
        system seen only once) — deliberately not guessed from a single
        data point.
        """
        systems = self.db.conn.execute(
            """
            SELECT DISTINCT fs.system_address, s.system_name
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.faction_name = ?
              AND NOT EXISTS (
                  SELECT 1 FROM dismissed_faction_systems d
                  WHERE d.faction_name = fs.faction_name AND d.system_address = fs.system_address
              )
            """,
            (faction_name,),
        ).fetchall()

        out: List[dict] = []
        for row in systems:
            system_address = row["system_address"]
            system_name = row["system_name"]
            prediction = self._predict_faction_in_system(system_address, faction_name)
            out.append({
                "system_address": system_address,
                "system_name": system_name,
                **prediction,
            })
        return out

    def _predict_faction_in_system(self, system_address: int, faction_name: str) -> dict:
        """
        Single-(system, faction) half of get_faction_predictions()'s
        computation — extracted so it can also be run for every faction in
        a system (see get_all_faction_predictions_for_system), not just one
        tracked faction. Same fields as one get_faction_predictions() entry,
        minus system_address/system_name (the caller already has those).
        """
        history = [
            dict(h) for h in self.db.conn.execute(
                """
                SELECT snapshot_date, influence FROM faction_snapshots
                WHERE system_address = ? AND faction_name = ? AND influence IS NOT NULL
                ORDER BY snapshot_date DESC
                LIMIT 14
                """,
                (system_address, faction_name),
            ).fetchall()
        ]

        trend = None
        if len(history) >= 2:
            newest, oldest = history[0]["influence"], history[-1]["influence"]
            if newest - oldest > 0.02:
                trend = "up"
            elif oldest - newest > 0.02:
                trend = "down"
            else:
                trend = "flat"

        our_influence = history[0]["influence"] if history else None

        days_in_expansion_range = None
        if our_influence is not None and our_influence >= 0.70:
            days_in_expansion_range = 0
            for h in history:
                if h["influence"] >= 0.70:
                    days_in_expansion_range += 1
                else:
                    break

        days_in_retreat_range = None
        if our_influence is not None and our_influence < 0.05:
            days_in_retreat_range = 0
            for h in history:
                if h["influence"] < 0.05:
                    days_in_retreat_range += 1
                else:
                    break

        conflict_risk = None
        if our_influence is not None and our_influence >= 0.07:
            rivals = self.db.conn.execute(
                """
                SELECT fs.faction_name, fs.influence
                FROM faction_snapshots fs
                WHERE fs.system_address = ? AND fs.faction_name != ?
                  AND fs.influence IS NOT NULL AND fs.influence >= 0.07
                  AND fs.snapshot_date = (
                      SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                      WHERE fs2.system_address = fs.system_address
                        AND fs2.faction_name = fs.faction_name
                  )
                """,
                (system_address, faction_name),
            ).fetchall()
            best, best_diff = None, None
            for r in rivals:
                diff = abs(r["influence"] - our_influence)
                if diff <= 0.05 and (best_diff is None or diff < best_diff):
                    best, best_diff = r, diff
            if best is not None:
                conflict_risk = {
                    "faction_name": best["faction_name"],
                    "influence": best["influence"],
                    "diff": best_diff,
                }

        active_war = None
        own_row = self.db.conn.execute(
            """
            SELECT faction_state, active_states, snapshot_date
            FROM faction_snapshots
            WHERE system_address = ? AND faction_name = ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (system_address, faction_name),
        ).fetchone()
        if own_row is not None and _row_is_at_war(own_row["faction_state"], own_row["active_states"]):
            war_rivals = self.db.conn.execute(
                """
                SELECT fs.faction_name, fs.influence, fs.faction_state, fs.active_states
                FROM faction_snapshots fs
                WHERE fs.system_address = ? AND fs.faction_name != ?
                  AND fs.snapshot_date = ?
                """,
                (system_address, faction_name, own_row["snapshot_date"]),
            ).fetchall()
            best_opponent = None
            for r in war_rivals:
                if not _row_is_at_war(r["faction_state"], r["active_states"]):
                    continue
                r_influence = r["influence"] if isinstance(r["influence"], (int, float)) else 0.0
                best_influence = best_opponent["influence"] if best_opponent and isinstance(best_opponent["influence"], (int, float)) else -1.0
                if best_opponent is None or r_influence > best_influence:
                    best_opponent = r
            if best_opponent is not None:
                active_war = {"faction_name": best_opponent["faction_name"], "influence": best_opponent["influence"]}
            else:
                active_war = {"faction_name": None, "influence": None}

        return {
            "influence": our_influence,
            "trend": trend,
            "days_in_expansion_range": days_in_expansion_range,
            "days_in_retreat_range": days_in_retreat_range,
            "conflict_risk": conflict_risk,
            "active_war": active_war,
        }

    def get_all_faction_predictions_for_system(self, system_address: int) -> List[dict]:
        """
        Prediction (trend/expansion/retreat/conflict/active-war) for every
        faction with a snapshot in this system, not just one tracked
        faction — used by the Player Faction tab's per-system history
        drill-down. Same fields as one get_faction_predictions() entry,
        minus system_address/system_name, plus faction_name. Sorted by
        current influence descending; entries with no known influence
        (None) sort last.
        """
        rows = self.db.conn.execute(
            "SELECT DISTINCT faction_name FROM faction_snapshots WHERE system_address = ?",
            (system_address,),
        ).fetchall()

        out: List[dict] = []
        for row in rows:
            faction_name = row["faction_name"]
            prediction = self._predict_faction_in_system(system_address, faction_name)
            prediction["faction_name"] = faction_name
            out.append(prediction)

        out.sort(key=lambda p: (p["influence"] is None, -(p["influence"] or 0.0)))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_faction_predictions_all_factions.py tests/test_active_war_opponent.py -v`
Expected: all PASS — the new tests confirm the extraction and new method, `test_active_war_opponent.py` confirms `get_faction_predictions` is unchanged.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS (matches the pre-existing count, plus the 8 new tests in this file).

- [ ] **Step 6: Commit**

```bash
git add persistence/repository.py tests/test_faction_predictions_all_factions.py
git commit -m "feat: add Repository.get_all_faction_predictions_for_system()"
```

---

### Task 2: UI — multi-faction history dialog (forecast pane + graph + table)

**Files:**
- Modify: `edc/ui/panels/player_faction_panel.py` (imports, new module-level constant near line 200, `_FactionHistoryDialog` class currently at lines 1889-1962)
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `Repository.get_all_faction_predictions_for_system(system_address: int) -> list[dict]` (Task 1) — each dict has `faction_name`, `influence`, `trend`, `days_in_expansion_range`, `days_in_retreat_range`, `conflict_risk`, `active_war`.
- Consumes: `Repository.get_faction_history(system_address: int) -> list[dict]` (already exists, unchanged) — each dict has `faction_name`, `snapshot_date`, `influence`, `government`, `allegiance`, `faction_state`, `happiness`, `active_states`, `pending_states`, `recovering_states`, `is_controlling`.
- Consumes: `_format_forecast(prediction: Optional[dict]) -> Tuple[str, str]` (already exists at `player_faction_panel.py:203-239`, unchanged) — `(text, color_hex)`.
- Consumes: `_parse_states(raw) -> List[str]` (already exists at `player_faction_panel.py:101`, unchanged).
- Produces: module-level `_FACTION_CHART_COLORS: List[str]` — an 8-entry hex color list, consumed only within this file.

This task has no automated test — this codebase has no Qt test fixture (`QApplication`) anywhere in `tests/`, confirmed via `grep -r QApplication tests/` returning nothing, and every other panel/dialog change this session ended with manual live verification instead. This task ends the same way.

- [ ] **Step 1: Add the `PyQt6-Charts` dependency**

In `requirements.txt`, add a new line after `PyQt6==6.10.2`:

```
PyQt6-Charts==6.10.0
```

Run: `pip install -r requirements.txt`
Expected: installs successfully; `python -c "from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis; print('ok')"` prints `ok`.

- [ ] **Step 2: Add imports**

In `edc/ui/panels/player_faction_panel.py`, change the `PyQt6.QtCore` import (line 17) to also bring in `QDate` and `QDateTime`:

```python
from PyQt6.QtCore import Qt, QObject, QThread, QStringListModel, QTimer, pyqtSignal, QDate, QDateTime
```

Add a new import immediately below the existing `PyQt6.QtWidgets` import block (after line 23):

```python
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis
```

- [ ] **Step 3: Add the faction-identity color palette**

Immediately above `_format_forecast` (before line 203), add:

```python
_FACTION_CHART_COLORS = [
    "#4D96FF", "#FFB347", "#6BCB77", "#FF6B6B",
    "#B983FF", "#FFD93D", "#4DD8C8", "#FF8FB1",
]
```

This is a faction-**identity** color (which line/name belongs to which faction), separate from `_format_forecast`'s **semantic** color (what kind of forecast it is) — both are used together in Step 5, never merged into one value.

- [ ] **Step 4: Rebuild `_FactionHistoryDialog.__init__`**

Replace the current `_FactionHistoryDialog` class (lines 1889-1962 — both `__init__` and `refresh`) with:

```python
class _FactionHistoryDialog(QDialog):
    """
    Non-modal per-system BGS history drill-down, opened by clicking a bucket
    table row's Influence cell. Shows every faction present in the system
    (not just the tracked one): a forecast line per faction, an
    influence-over-time graph, and a plain day-by-day table — nothing new
    is persisted here, this only displays what save_faction_snapshot()
    already records daily.
    """

    def __init__(self, panel: "PlayerFactionPanel", system_address: int, system_name: str):
        super().__init__(None)
        self._panel = panel
        self._system_address = system_address
        self.setWindowTitle(f"BGS History — {system_name}")
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.resize(640, 700)

        layout = QVBoxLayout(self)

        self._forecast_label = QLabel("")
        self._forecast_label.setWordWrap(True)
        self._forecast_label.setTextFormat(Qt.TextFormat.RichText)
        self._forecast_label.setStyleSheet("background:transparent; border:none; padding:4px;")
        layout.addWidget(self._forecast_label)

        self._chart = QChart()
        self._chart.setBackgroundBrush(QColor("#080f18"))
        self._chart.setTitleBrush(QColor("#c8c8c8"))
        self._chart.legend().setLabelColor(QColor("#c8c8c8"))
        self._chart_view = QChartView(self._chart)
        self._chart_view.setMinimumHeight(220)
        layout.addWidget(self._chart_view)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Date", "Faction", "Influence", "Active State"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 90)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        try:
            predictions = self._panel._repo.get_all_faction_predictions_for_system(self._system_address)
        except Exception:
            log.exception("Failed to load faction predictions for system %s", self._system_address)
            predictions = []

        colors: Dict[str, str] = {
            p["faction_name"]: _FACTION_CHART_COLORS[i % len(_FACTION_CHART_COLORS)]
            for i, p in enumerate(predictions)
        }

        forecast_lines = []
        for p in predictions:
            fname = p["faction_name"]
            identity_color = colors.get(fname, _FACTION_CHART_COLORS[0])
            text, semantic_color = _format_forecast(p)
            forecast_lines.append(
                f'<div style="margin-bottom:2px;">'
                f'<span style="color:{identity_color};font-weight:700;">{fname}</span>'
                f' — <span style="color:{semantic_color};">{text}</span>'
                f'</div>'
            )
        self._forecast_label.setText(
            "".join(forecast_lines) if forecast_lines else
            '<span style="color:#444444;">No factions tracked in this system yet.</span>'
        )

        try:
            history = self._panel._repo.get_faction_history(self._system_address)
        except Exception:
            log.exception("Failed to load faction history for system %s", self._system_address)
            history = []

        by_faction: Dict[str, list] = {}
        for h in history:
            by_faction.setdefault(h.get("faction_name") or "Unknown", []).append(h)

        self._chart.removeAllSeries()
        for axis in list(self._chart.axes()):
            self._chart.removeAxis(axis)

        ordered_factions = [p["faction_name"] for p in predictions if p["faction_name"] in by_faction]
        ordered_factions += [f for f in by_faction if f not in ordered_factions]

        axis_x = QDateTimeAxis()
        axis_x.setFormat("MMM d")
        axis_x.setLabelsColor(QColor("#888888"))
        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setLabelFormat("%d%%")
        axis_y.setLabelsColor(QColor("#888888"))
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)

        for i, fname in enumerate(ordered_factions):
            color = colors.get(fname, _FACTION_CHART_COLORS[i % len(_FACTION_CHART_COLORS)])
            series = QLineSeries()
            series.setName(fname)
            series.setColor(QColor(color))
            for h in sorted(by_faction[fname], key=lambda r: r.get("snapshot_date") or ""):
                infl = h.get("influence")
                if not isinstance(infl, (int, float)):
                    continue
                qd = QDate.fromString(h.get("snapshot_date") or "", "yyyy-MM-dd")
                if not qd.isValid():
                    continue
                qdt = QDateTime(qd)
                series.append(qdt.toMSecsSinceEpoch(), infl * 100)
            if series.count():
                self._chart.addSeries(series)
                series.attachAxis(axis_x)
                series.attachAxis(axis_y)

        self._table.setRowCount(len(history))
        for row, h in enumerate(history):
            fname = h.get("faction_name") or "Unknown"
            date_item = QTableWidgetItem(h.get("snapshot_date") or "—")
            faction_item = QTableWidgetItem(fname)
            faction_item.setForeground(QColor(colors.get(fname, _FACTION_CHART_COLORS[0])))
            infl = h.get("influence")
            infl_item = _NumericTableWidgetItem(
                f"{infl * 100:.1f}%" if isinstance(infl, (int, float)) else "—",
                float(infl) if isinstance(infl, (int, float)) else -1.0,
            )
            infl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            active_names = [h.get("faction_state")] if h.get("faction_state") and h.get("faction_state") != "None" else []
            active_names += [st for st in _parse_states(h.get("active_states")) if st not in active_names]
            state_item = QTableWidgetItem(", ".join(active_names) if active_names else "—")
            self._table.setItem(row, 0, date_item)
            self._table.setItem(row, 1, faction_item)
            self._table.setItem(row, 2, infl_item)
            self._table.setItem(row, 3, state_item)
```

- [ ] **Step 5: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/player_faction_panel.py', encoding='utf-8').read())"`
Expected: no output (parses cleanly).

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS (no test in this repo exercises this dialog directly, so this only confirms nothing else broke — e.g. an import error at module load would fail collection for every test in this file's package).

- [ ] **Step 7: Manual live verification**

Launch the app, go to the Player Faction tab, open a status bucket tile, click a row's Influence cell. Confirm:
- Dialog title is `BGS History — <system name>`.
- Forecast pane shows one line per faction actually present in that system (not just the tracked one), each faction name in a distinct color, forecast phrase in its existing semantic color (e.g. red for "At War").
- Graph renders one colored line per faction (colors matching the forecast pane), x-axis shows dates, y-axis shows 0-100%.
- Table below shows Date/Faction/Influence/Active State rows for every faction, Faction column text colored to match.
- No crash/traceback in the console when opening, refreshing (jump systems and reopen), or closing the dialog.

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/player_faction_panel.py requirements.txt
git commit -m "feat: show every faction's BGS history, forecast, and a trend graph in the per-system drill-down"
```

---

### Task 3: Remove the now-redundant Intel tab BGS History card

**Files:**
- Modify: `edc/ui/panels/intel_panel.py` (card construction ~line 512-533, `refresh()` ~line 789-824)
- Modify: `edc/ui/main_window.py` (`_refresh_intel` ~line 3950-3968)

**Interfaces:**
- Consumes: nothing new.
- Produces: `IntelPanel.refresh(self, state, farming_locations, farming_candidates=None)` — `faction_history` parameter removed (was 3rd positional/keyword parameter).

This task is independent of Tasks 1-2 (it deletes code, no dependency on the new repository method or dialog) but is sequenced last so the richer Player Faction tab drill-down is confirmed working (Task 2, Step 7) before its simpler Intel tab counterpart is deleted.

- [ ] **Step 1: Re-read `intel_panel.py` fresh and remove the BGS history card**

Read `edc/ui/panels/intel_panel.py` around lines 505-535 to confirm current line numbers (this file is not on the project's frequently-stale list, but re-read fresh per this session's established practice before editing). Remove the entire `# ── BGS history card ──` block — from the comment through the `self._content_layout.addWidget(bgs_frame)` line (the block building `bgs_frame`, `bgs_l`, `bgs_hdr`, and `self.bgs_display`).

- [ ] **Step 2: Remove the BGS history block from `refresh()`**

In the same file, in `refresh(self, state, farming_locations, faction_history=None, farming_candidates=None)`:
- Remove the `# ── BGS history ──` block (the `history_html` loop and the `self.bgs_display.setText(...)` call).
- Remove the now-unused `faction_history=None` parameter from the method signature, leaving:

```python
    def refresh(self, state, farming_locations, farming_candidates=None):
```

- [ ] **Step 3: Update `main_window.py`'s `_refresh_intel`**

Re-read `edc/ui/main_window.py` around lines 3950-3968 fresh (this file is on the project's frequently-stale list — always re-read before editing). Remove the `faction_history` local and its computation:

```python
        system_address = getattr(self.state, "system_address", None)
        faction_history = []
        if isinstance(system_address, int):
            try:
                faction_history = self.repo.get_faction_history(system_address)
            except Exception:
                log.exception("Failed to load faction history")
```

and update the call:

```python
        self.intel_panel.refresh(
            self.state, self.farming_locations, farming_candidates
        )
```

(The second call site, ~line 4174-4177, already calls `self.intel_panel.refresh(self.state, self.farming_locations)` with no 3rd argument — confirm during this step that it still matches the new signature; no edit needed there since `farming_candidates` already defaults to `None`.)

- [ ] **Step 4: Verify no dangling references**

Run: `grep -rn "faction_history\|bgs_display\|bgs_frame" edc/ui/panels/intel_panel.py edc/ui/main_window.py`
Expected: no output (every reference removed).

- [ ] **Step 5: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/intel_panel.py', encoding='utf-8').read()); ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Manual live verification**

Launch the app, open the Intel tab. Confirm the "BGS HISTORY — THIS SYSTEM" card is gone and every other Intel tab card (POIs, Farming Locations, Surface Scan, Nearest Farming Opportunities, Odyssey Farming Candidates, Full Farming Guide) still renders and refreshes normally when jumping systems.

- [ ] **Step 8: Commit**

```bash
git add edc/ui/panels/intel_panel.py edc/ui/main_window.py
git commit -m "refactor: remove Intel tab BGS History card, superseded by the Player Faction tab drill-down"
```
