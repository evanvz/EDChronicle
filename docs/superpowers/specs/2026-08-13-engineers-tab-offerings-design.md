# Engineers Tab — Section Order, Category Tag, Upgrade Summary — Design

## Context

Follow-up to the visual pass just shipped (color-coded 3-column grid, commits `7f7783c`..`c9ee8ce` on `main`). Live use surfaced three more gaps in `_EngineersTab` (`edc/ui/panels/engineering_panel.py`):

1. Section order (UNLOCKED, IN PROGRESS, NOT ENCOUNTERED) puts what's already done first — the user wants what's actionable (In Progress) first instead.
2. Nothing on a card indicates whether an engineer is a Ship engineer or a Suit & Weapons (Odyssey) engineer.
3. Nothing on a card indicates what that engineer actually unlocks — a card and the Ships/Suits & Weapons tabs' own per-blueprint engineer columns are currently disconnected.

Two behaviors the user asked about and are already correct, no work needed: card status already updates live off real `EngineerProgress` journal events (the rebuild-skip guard added in the last review's final fix only skips a rebuild when nothing changed, not real updates), and all 38 real engineers already always render, including ones never encountered (grouped into Not Encountered with their static requirement text).

## Research

Both the ship and Odyssey data already carry the reverse mapping needed (blueprint/module → engineers), just not indexed the other way (engineer → blueprints/modules):

- `EngineeringBlueprintTable.engineers_for(fdname, grade) -> List[str]` — per blueprint, per grade. A blueprint's `grade_engineers` dict can list different engineers at different grades, so "does this engineer offer this blueprint" means checking membership across ALL of that blueprint's grades, not just one.
- `OdysseyEngineeringTable.module_engineers(kind, key) -> List[str]` — per suit/weapon module (`kind` is `"suit"` or `"weapon"`), flat (no per-grade split).

Building the reverse index means one full pass over `blueprint_names()` × grades and `suit_module_keys()` + `weapon_module_keys()` — not expensive (dozens of blueprints/modules, not thousands), but expensive enough, and called often enough by a per-refresh path, that it should be computed once and cached, not recomputed on every `_EngineersTab.refresh()`. `refresh()` was just fixed (previous plan's final review) to skip rebuilding when nothing changed — reintroducing an uncached per-refresh scan here would undercut that fix on the first refresh after any change.

## Design

### 1. Section order

`_EngineersTab.refresh()`'s and `__init__`'s section loop changes from `("unlocked", "in_progress", "not_encountered")` to `("in_progress", "not_encountered", "unlocked")`. Pure reorder of the existing tuple, both in `__init__` (header/grid creation order) and `refresh()` (population order) — no other logic changes.

### 2. Reverse index — cached on the two table classes

New methods, computed lazily on first call and cached alongside each class's existing `_load()`-time data (both classes already follow this cache-on-load pattern for their other lookups):

- `EngineeringBlueprintTable.engineer_blueprint_count(engineer_name: str) -> int` — count of distinct blueprints (fdnames) this engineer appears in `engineers_for()` for, at any grade.
- `OdysseyEngineeringTable.engineer_module_count(engineer_name: str) -> int` — count of distinct suit + weapon module keys this engineer appears in `module_engineers()` for.

Both back onto a single cached `Dict[str, int]` built once (invalidated the same way each class's other caches already are, via their existing `_load(force=...)` mtime-check pattern — no new invalidation mechanism needed, just building the count dict inside the same method that already rebuilds on file change).

### 3. Category tag

In `_EngineersTab._engineer_html`, right after the engineer's name: if `engineer_blueprint_count(name) > 0`, append `[Ship]`; if `engineer_module_count(name) > 0` (suit or weapon), append `[Suit & Weapons]` — both together become `[Ship, Suit & Weapons]` for engineers offering both. An engineer with zero in both (data gap, per `engineers_for()`'s own docstring noting coverage isn't 100%) shows no tag rather than a misleading `[Unknown]`.

### 4. Upgrade summary line

One new line on the card, below the status line and above the existing requirement fields: `f"{ship_count} ship blueprint{'s' if ship_count != 1 else ''}, {odyssey_count} suit & weapon mod{'s' if odyssey_count != 1 else ''}"`, styled the same muted grey as the existing requirement-field lines (`#888888`, `12px`). Omit the whole line (not a "0 of everything" line) if both counts are zero.

### Testing

The two new count methods are synthetic-testable against the existing JSON fixtures/loaders (construct a table instance, assert a known engineer's count matches manual inspection of `settings/engineering_blueprints.json`/`odyssey_engineering.json`). The tag/summary rendering and section reorder are rendering-only, verified visually/headlessly, matching this tab's established testing convention.
