# BGS History Drill-Down — All Factions + Forecast + Graph — Design

## Context

`_FactionHistoryDialog` (`edc/ui/panels/player_faction_panel.py:1889`) already
exists (shipped in commit `66185db`, per the 2026-08-09 spec): a non-modal
`QDialog`, opened by clicking a bucket-dialog row's Influence cell
(`_FactionBucketDialog._on_cell_clicked`, `player_faction_panel.py:2215-2231`),
titled `"BGS History — {system_name}"`, showing a Date/Influence/Active State
table for **one faction** (the tracked one) via
`Repository.get_faction_history(system_address, faction_name)`.

This plan broadens it: same trigger, same dialog class, but shows **every**
faction present in that system, adds a per-faction forecast line, and adds a
multi-line influence-over-time graph. Once this exists, the Intel tab's
"BGS HISTORY — THIS SYSTEM" card is redundant (current-system-only, no
forecast, no graph) and is removed.

## What already supports this (no schema change)

- `Repository.get_faction_history(system_address, faction_name=None)`
  (`persistence/repository.py:1827`) already returns **all** factions for a
  system when called without `faction_name` — this is exactly what
  `intel_panel.py` already uses. No change needed to this method.
- `faction_snapshots` is already pruned to a 30-day rolling window per
  `(system_address, faction_name)` inside `save_faction_snapshot()`
  (`persistence/repository.py:440`), so history size per faction is already
  bounded — no new LIMIT needed in the dialog's query.
- `Repository.get_faction_predictions(faction_name)`
  (`persistence/repository.py:523-678`) computes trend/expansion/retreat/
  conflict/active-war for one faction across every system it's tracked in.
  Its per-row body (lines 560-677) is a self-contained computation over a
  single `(system_address, faction_name)` pair — has no dependency on the
  outer loop's `systems` list beyond those two values.
- `_format_forecast(prediction)` (`player_faction_panel.py:203-239`) already
  turns one prediction dict into `(text, color)` — reusable per-faction as-is.

## Backend changes — `persistence/repository.py`

1. Extract lines 560-677 (the per-row body of `get_faction_predictions`) into
   a new private method:

   ```python
   def _predict_faction_in_system(self, system_address: int, faction_name: str) -> dict:
       # exact body currently inlined at lines 564-677, verbatim,
       # returning the same dict shape currently appended to `out`
   ```

   `get_faction_predictions` becomes: build the `systems` list (unchanged),
   then `out = [self._predict_faction_in_system(row["system_address"], faction_name) | {"system_name": row["system_name"]} for row in systems]`
   (or equivalent — the returned dict shape and field values must not
   change, since existing callers depend on it).

2. New public method:

   ```python
   def get_all_faction_predictions_for_system(self, system_address: int) -> list[dict]:
       """
       Prediction (trend/expansion/retreat/conflict/active-war) for every
       faction with a snapshot in this system, not just one tracked
       faction. Same fields as get_faction_predictions() entries, minus
       system_address/system_name (caller already knows the system), plus
       faction_name. Sorted by current influence descending (None last).
       """
   ```

   Implementation: query `SELECT DISTINCT faction_name FROM faction_snapshots
   WHERE system_address = ?` (latest-snapshot scope not required here — a
   faction that ever had a snapshot in this system should get a forecast
   row, `_predict_faction_in_system` itself only looks at the last 14 days
   and current influence). For each faction_name, call
   `self._predict_faction_in_system(system_address, faction_name)`, add
   `"faction_name": faction_name` to the result dict. Sort by `influence`
   descending, `None` influence sorted last.

## UI changes — `edc/ui/panels/player_faction_panel.py`

**New module-level constant**, placed near `_format_forecast` (~line 200):

```python
_FACTION_CHART_COLORS = [
    "#4D96FF", "#FFB347", "#6BCB77", "#FF6B6B",
    "#B983FF", "#FFD93D", "#4DD8C8", "#FF8FB1",
]
```

Cycled with `_FACTION_CHART_COLORS[i % len(_FACTION_CHART_COLORS)]` where `i`
is the faction's index in the influence-descending order returned by
`get_all_faction_predictions_for_system`. This is a **faction-identity**
color (which line is which faction in the chart, and which color the
faction's name renders in, in both the forecast pane and the table) —
distinct from `_format_forecast`'s returned color, which stays a
**semantic** color (red=war/retreat, amber=conflict, green=expansion, grey=
flat/no-data) exactly as today. A forecast line therefore renders as: faction
name in its identity color, forecast phrase in its semantic color.

**`_FactionHistoryDialog.__init__`** (currently lines 1899-1932): dialog
grows from a single table to three stacked sections. Resize from `(520,
420)` to `(640, 700)`. New layout, top to bottom:

1. **Forecast pane** — `QLabel` (rich text, word-wrap), one line per
   faction: `<span style="color:{identity_color};font-weight:700;">{faction_name}</span> — <span style="color:{semantic_color};">{forecast_text}</span>`. Replaces the current single `self._forecast_label` (which showed only the tracked faction's forecast).
2. **Graph** — new `PyQt6.QtCharts.QChartView` containing a `QChart` with
   one `QLineSeries` per faction, x-axis a `QDateTimeAxis` (real date
   spacing, so a missing day in a faction's history shows as a gap rather
   than being compressed away) — `snapshot_date` strings (`YYYY-MM-DD`)
   parsed with `QDate.fromString(s, "yyyy-MM-dd")` then converted to
   `QDateTime` at midnight for each point's x value — and
   `influence * 100` on the y-axis via `QValueAxis`, 0-100 range, label
   suffix `%`. Each series colored via
   `QLineSeries.setColor(QColor(identity_color))`, `setName(faction_name)`
   for the legend. Reasonable fixed height (e.g.
   `chart_view.setMinimumHeight(220)`).
3. **Table** (existing widget, widened) — columns become `["Date",
   "Faction", "Influence", "Active State"]` (was `["Date", "Influence",
   "Active State"]` — insert Faction as new column 1, shifting Influence to
   2 and Active State to 3). Faction cell text colored with that faction's
   identity color (`QTableWidgetItem.setForeground(QColor(identity_color))`)
   for visual linking to the chart/forecast pane. Column resize modes:
   Date/Faction/Influence `Interactive` (widths 100/140/90), Active State
   `Stretch` — same pattern as today, just one more `Interactive` column.

**`_FactionHistoryDialog.refresh()`** (currently lines 1934-1962):
- Replace the single `get_faction_predictions` lookup
  (`self._panel._last_predictions.get(self._system_address)`) with
  `predictions = self._panel._repo.get_all_faction_predictions_for_system(self._system_address)` (wrapped in the same try/except-and-log pattern already used for the history query below it). Build the faction→identity-color map from this list's order.
- Replace the single `self._panel._repo.get_faction_history(self._system_address, self._panel._faction_name)` call with
  `self._panel._repo.get_faction_history(self._system_address)` (drop the
  faction filter — this alone is what makes the table multi-faction; no
  other change to this call).
- Build the forecast pane HTML from `predictions` (one `<div>` per entry,
  same identity/semantic coloring as above).
- Populate the chart: group `history` rows by `faction_name`, one
  `QLineSeries` per faction in the same influence-descending order as
  `predictions` (a faction present in `history` but absent from
  `predictions` — e.g. only one data point, no current influence — still
  gets a line, appended after the ordered ones, next available palette
  color).
- Populate the table with the extra Faction column, same row-per-
  `(faction, date)` shape as `history` already provides, same overall sort
  (`snapshot_date` DESC, `faction_name` ASC, as `get_faction_history`
  already orders).

**`_FactionBucketDialog._on_cell_clicked`** (lines 2215-2231): unchanged —
still triggers on column 1 (Influence), still constructs
`_FactionHistoryDialog(self._panel, system_address, system_name)`.

**Docstring update**: `_FactionHistoryDialog`'s class docstring (lines
1890-1896) currently says "per-system BGS history" scoped to the tracked
faction — update to reflect it now covers every faction in the system.

## Dependency

`requirements.txt`: add `PyQt6-Charts==6.10.0` (closest available release to
the pinned `PyQt6==6.10.2`; PyPI's latest is 6.11.0 as of this spec, but
6.10.0 is the same minor line as the pinned base package). First charting
library in this app — confirmed via `requirements.txt` and a repo-wide grep
that none exists today.

## Intel tab removal — `edc/ui/panels/intel_panel.py` + `edc/ui/main_window.py`

- `intel_panel.py`: remove the `bgs_frame` construction block (lines
  513-533, the `# ── BGS history card ──` section through
  `self._content_layout.addWidget(bgs_frame)`) and the `self.bgs_display`
  attribute it creates.
- `intel_panel.py::refresh()`: remove the `# ── BGS history ──` block
  (lines 794-824) and the now-unused `faction_history` parameter from the
  method signature (line 789) — confirm no other call site still passes a
  3rd positional/keyword arg for it (the two call sites in `main_window.py`
  are both covered below).
- `main_window.py::_refresh_intel` (lines 3950-3968): remove the
  `faction_history` local (lines 3951-3957) and its argument in the
  `self.intel_panel.refresh(...)` call (line 3966-3968) — the
  `get_faction_history` call this deletes was only feeding the removed
  card, nothing else in this method uses it.
- `main_window.py`'s second call site (lines 4174-4177) already omits
  `faction_history` — no change needed there.

## Out of scope

- No change to `_FactionBucketDialog`'s own table/columns.
- No change to how/when `faction_snapshots` rows are captured or pruned.
- No zoom/pan/tooltip interactivity on the chart beyond what
  `QChartView`/`QChart` default to — a static multi-line view, consistent
  with "smallest thing that works" for a v1.
- No removal of `get_faction_predictions` (still used by the bucket
  dashboard's own per-tracked-faction Forecast-adjacent features elsewhere
  in this file) — only its internals are refactored, its signature and
  return values are unchanged.
