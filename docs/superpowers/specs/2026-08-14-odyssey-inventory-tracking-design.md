# Odyssey Inventory Tracking (ShipLocker + Backpack) — Design

## Context

Live use surfaced three related bugs in Odyssey material tracking: after bartender trades (`TradeMicroResources`), held-material counts don't update; the Odyssey tab's material names sometimes don't display correctly; and it doesn't appear to track all of a player's actual material categories.

## Research (external verification — sources at end)

Confirmed against the Elite Dangerous journal's own documented schema, plus the user's real, live journal file from this session:

- **`ShipLocker`** fires as a *bare notification* after any change (`{"event":"ShipLocker"}`, no `Items` array) — the actual current full contents are written to a companion file, `ShipLocker.json`, in the journal directory. EDChronicle already solves this exact pattern for `Cargo.json` (`MainWindow._load_cargo_inventory()`), but nothing equivalent exists for `ShipLocker.json` — the current `ShipLocker` handler only updates state when `Items` happens to be present inline (rare; confirmed in the live journal this only happens on the FIRST `ShipLocker` event of a session, same as `Cargo`).
- **`ShipLocker.json`** has FOUR top-level arrays — `Items`, `Components`, `Data`, `Consumables` (confirmed by reading the user's actual live file) — but the current code only ever parses `Items`. Components and Data are the categories most suit/weapon engineering materials fall into, so this alone likely explains most of the "materials not tracked" symptom.
- **`Backpack`** (full snapshot) has the identical bare-event-plus-companion-file pattern (`Backpack.json`), also unhandled anywhere today.
- **`BackpackChange`** is different and self-contained: it carries `Added`/`Removed` arrays directly in the event (each item has `Name`, `Name_Localised`, `Count`, `Type` — "Consumable"/"Component"/"Item"), no file read required.
- The user's real journal confirms bartender trades trigger the bare `ShipLocker` notification specifically (not `Backpack`) — consistent with community documentation that the Ship Locker is the primary store engineering material availability is checked against.
- Material *names*: cross-checked every symbol from the user's real trades against `settings/odyssey_material_names.json` (EDCD/FDevIDs-sourced) — full coverage, correct names. So the static fallback table itself isn't the gap; the more likely explanation is that Components/Data-category materials were never being captured into live state at all (no name lookup possible), which this fix addresses as a side effect. If names are still wrong after this ships, that's evidence of a narrower, separate bug worth a fresh look.

## Design

### 1. `ShipLocker.json` re-read on the bare event

Mirrors `_load_cargo_inventory()` exactly: a new `MainWindow._load_shiplocker_inventory()` reads `<journal_dir>/ShipLocker.json`, parses all four arrays (`Items`, `Components`, `Data`, `Consumables`), and updates state. Wired the same way as `Cargo`: `if name == "ShipLocker": self._load_shiplocker_inventory()`.

### 2. `Backpack.json` re-read + `BackpackChange` incremental updates

New `MainWindow._load_backpack_inventory()` (same file-read pattern) wired to the bare `Backpack` event. `BackpackChange` is handled separately in the event engine (like `MaterialCollected`/`MaterialDiscarded` already are) — apply `Added`/`Removed` deltas directly to backpack state, no file read.

### 3. New state fields

`state.shiplocker_items`/`shiplocker_localised` (existing, currently Items-only) get populated from all four ShipLocker categories combined into one flat dict, matching the existing single-dict shape `_held_count()` already expects (a symbol is only ever in one category, so no collision risk). New `state.backpack_items`/`backpack_localised`, same shape, populated from Backpack's four categories.

### 4. Held-count sums both pools

`_OdysseyEngineeringTab._held_count()` in `edc/ui/panels/engineering_panel.py` changes from reading `shiplocker_items` alone to summing `shiplocker_items.get(symbol, 0) + backpack_items.get(symbol, 0)` — matching the engineer terminal's real combined-availability display. `_material_name()` checks both localised dicts (ShipLocker first, then Backpack, then the static fallback table), same fallback order concept as today.

### 5. Friendlier category naming (user's added note)

Wherever a category label is shown to the user for Odyssey materials, use the game's own player-facing terms rather than internal journal type strings — confirmed via research: in-game these are called **Goods** (`Item`), **Assets** (`Component` — with Chemicals/Circuits/Tech sub-groupings, not tracked separately here), and **Data** (`Data`). `Consumable` stays "Consumables" (health packs, energy cells — not an engineering material category, but still player inventory). This is a labeling-only change wherever the UI currently shows a raw category string, not a new feature.

### Testing

The `ShipLocker.json`/`Backpack.json` parsing logic is synthetic-testable (write a fixture file with all four arrays, assert the combined dict is built correctly) — matches `_load_cargo_inventory()`'s untested-but-simple precedent, though this plan should add real tests since correctness here directly caused the reported bugs. `BackpackChange`'s Added/Removed delta application is synthetic-testable the same way `MaterialCollected`/`MaterialDiscarded` presumably already are (check for existing tests of those handlers as the pattern to match). UI held-count/name changes verified visually per this tab's established convention, ideally against a real live bartender trade in the next play session.

## Sources

- [ShipLocker event schema](http://schemas.edomh.nl/ShipLocker.html)
- [Backpack event schema](http://schemas.edomh.nl/Backpack.html)
- [BackpackChange event schema](http://schemas.edomh.nl/BackpackChange.html)
- [TradeMicroResources event schema](http://schemas.edomh.nl/TradeMicroResources.html)
- [Elite Dangerous Journal documentation](https://elite-journal.readthedocs.io/)
- User's own live journal file, `Journal.2026-08-13T191308.01.log`, and companion `ShipLocker.json`/`Backpack.json`/`Cargo.json` files, read directly during this investigation.
