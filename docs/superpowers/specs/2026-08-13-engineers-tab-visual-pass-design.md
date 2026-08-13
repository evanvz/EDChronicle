# Engineers Tab Visual Pass — Design

## Context

The Engineers Reference Tab (`_EngineersTab` in `edc/ui/panels/engineering_panel.py`, built earlier this session) lists all in-game engineers grouped into three sections — UNLOCKED, IN PROGRESS, NOT ENCOUNTERED — with a static-reference-text card per engineer. Two usability gaps identified after live use: every card looks the same regardless of status (all use the same neutral card styling and orange status text), making it hard to scan for what's actually unlocked at a glance; and each card is full-width, one per row, wasting the tab's available horizontal space and forcing a lot of scrolling to see the full engineer roster.

## Research

`state.engineer_progress` (populated from the game's `EngineerProgress` journal event, persisted across restarts via `EngineerProgressStore`) only reports whole-engineer status: `rank` (int or None) and `progress` (a string like "Invited"). There is no per-requirement (Discover/Meet/Unlock/Referral) completion tracking anywhere in the data — those four fields in `engineer_requirements.json` are static reference text only. This means "completed" can only be expressed at the whole-engineer level (the existing `unlocked` / `in_progress` / `not_encountered` grouping), not per individual requirement line.

The current implementation builds each of the three sections as a single concatenated HTML string rendered in one `QLabel` per section (`self._sections[key].setText(html)`, built by `_engineer_html()` per engineer and joined). This is why layout today is a single vertical stack — a `QLabel` has no grid/column concept, so a multi-column layout requires per-card widgets instead of one HTML blob per section.

## Design

### Colors

Each section keeps its existing header (UNLOCKED / IN PROGRESS / NOT ENCOUNTERED), but individual cards now carry a status-matched accent:

| Status | Left-border accent | Status text color | Extra |
|---|---|---|---|
| Unlocked | `#6BCB77` (green — this app's existing "ok" color, already used by the service-health indicator and other panels) | `#6BCB77` | `✓ ` prefix on the status line |
| In Progress | `#FFB347` (amber — already used for this tab's status text today) | `#FFB347` | none |
| Not Encountered | `#555555` | `#888888` | card at ~75% opacity |

The checkmark is the only "completion" signal available, since (per Research) only whole-engineer status is trackable — it marks Unlocked, not individual requirement lines.

### Layout

Each section's engineer list changes from one full-width `QLabel`-rendered-HTML-blob per section to a 3-column `QGridLayout` of individual card widgets within that section, wrapping to additional rows as needed. Three columns was chosen (over 2, 4, or a responsive/auto-fit count) as the best balance of information density per card versus reading through mockups.

### Implementation shape

`_engineer_html()` currently returns one HTML fragment string appended into a per-section blob. This becomes a per-engineer widget builder instead — likely a small `QLabel` per card (rich-text HTML is still fine for the inside of one card, since Qt's `QLabel` richtext supports styled multi-line content), each one placed into its section's `QGridLayout` at `(row, col)` computed from the engineer's position in that section's sorted list (`col = i % 3`, `row = i // 3`). The three per-section `QLabel`s (`self._sections[key]`) are replaced by three per-section `QGridLayout`s, each cleared and repopulated on `refresh()` the same way the current code rebuilds its HTML string on every refresh (clear existing grid items, rebuild from `self._blueprints.all_engineer_names()` + `state.engineer_progress`, same as today).

### No data or architecture changes

This is a pure `_EngineersTab` internals change — no new files, no new state fields, no new journal event handling. `EngineeringPanel.refresh()`'s call into `self._engineers_tab.refresh(state)` and the `showEvent` re-population hook (added in the bugfix immediately before this design) are unchanged.

### Testing

No new business logic — grouping (`_status_for`) and requirement text lookup are unchanged, only how each engineer's information is rendered. No new automated tests; verified visually in the running app, matching this project's convention for panel-level UI changes and this tab's own original build.
