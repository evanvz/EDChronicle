# Odyssey Farming Candidates — Design

## Context

User asked which Odyssey settlement building types (EXT/RES/IND/HAB/CMD/STO/PWR)
and settlement conditions are safe to loot for on-foot suit/weapon materials
without resistance. Community research (see Sources below) converged on:
abandoned settlements (no power, no NPCs, no alarms), Anarchy-government
systems (no local law, can disable alarms and loot freely with no crime
consequence), and Power Generator Reactivation missions in war-state systems
(grants legitimate clearance to loot a manned settlement without triggering
hostility).

EDChronicle's Intel tab already has a farming-guide pattern for this class of
problem: `settings/elite_farming_locations.json`, loaded by
`edc/core/farming_locations.py::FarmingLocations`, organized into categories
(`encoded`, `raw`, `manufactured`, `odyssey_onfoot`, `guardian`, `thargoid`),
rendered as cards in `edc/ui/panels/intel_panel.py`. `odyssey_onfoot` already
has 4 curated entries, including a stub noting "use the galaxy map or external
tools to find factions in Pirate Attack state and farm settlements there" —
this plan replaces that "external tools" gap with EDChronicle's own tracked
data, since `faction_snapshots` (freshness-aware as of the prior plan this
session) already records `government`, `faction_state`, and `active_states`
per system.

## Design

### 1. Static content (data-only, no code change)

Extend `settings/elite_farming_locations.json`'s `odyssey_onfoot` array and
`bgs_tips` with settlement-safety guidance drawn from the research:

- Abandoned settlements: no power/NPCs/alarms, walk in and loot.
- Anarchy-government systems: disable alarms once inside, loot freely, no
  crime consequence.
- Power Generator Reactivation missions (war-state systems): legitimate
  level-3 clearance to loot a manned settlement without triggering hostility;
  needs Maverick suit + Arc Cutter + Energy Link to enter powered-down
  buildings.
- Building-type hints: EXT (extraction) and IND (industrial) buildings skew
  toward Manufactured materials; STO (storage) skews toward Goods.
- Cross-reference to the existing Dav's Hope entry (already present under
  `manufactured`) as a concrete abandoned-settlement example.

Pure JSON edit. `FarmingLocations` already parses arbitrary fields per
record (`note`, `method`, `key_materials`, etc.) — no loader changes needed.

### 2. Dynamic query — `Repository.get_odyssey_farming_candidates()`

New method in `persistence/repository.py`. For every system with a
`faction_snapshots` row where `is_controlling = 1` (the controlling faction
sets local government/law, which determines whether the system is actually
Anarchy and what BGS state is in effect — matches how safety works in-game),
take the most recent snapshot per system and classify it as a candidate if:

- `government == "Anarchy"`, OR
- `faction_state` (or any entry in the parsed `active_states` JSON) is one of:
  `war`, `civilwar`, `pirateattack`, `civilunrest`, `infrastructurefailure`
  (matched lowercase/no-space, identical convention to
  `player_faction_panel.py`'s existing `_parse_states()` + `_BUCKET_DEFS`
  classification — reused, not reimplemented).

No squadron-faction filter — scans every system ever recorded, regardless of
which faction is being tracked for BGS purposes, per explicit scope decision.

Sort: freshest `data_timestamp` first (reuses the freshness column shipped
in the prior plan this session). Cap: top 20.

Returns, per candidate: `system_name`, `matched_signals` (list, e.g.
`["Anarchy", "Pirate Attack"]`), `data_timestamp` (for computing a
human-readable age like "3 days ago" at the UI layer).

### 3. UI — new Intel panel card

`edc/ui/panels/intel_panel.py`: new card "ODYSSEY FARMING CANDIDATES",
placed after the existing "SURFACE SCAN — FARMING MATCHES" card, same visual
pattern (`QFrame` + header `QLabel` + rich-text body `QLabel`, matching the
existing cards' style/margins/colors — pick an unused accent color from the
same family already in use, e.g. a muted purple/violet frame to stay visually
distinct from the existing cyan/amber/green cards).

Each row: system name, matched signal(s), and freshness ("3 days ago" /
"today"). Empty state: "No tracked systems currently match — data comes from
systems you've visited or refreshed." Refresh timing follows the panel's
existing `refresh(state)` call pattern — query runs each refresh, not cached,
since `faction_snapshots` changes over a session.

## Testing

- `get_odyssey_farming_candidates()`: fully synthetic-testable — insert known
  `faction_snapshots` rows (Anarchy government, various states, various
  `is_controlling` values, various `data_timestamp`s) into a real temp
  SQLite DB, confirm correct classification, sort order, and the 20-item cap.
- UI card: confirmed visually (renders correctly with 0, 1, and many
  candidates) — no live journal event needed, since this reads existing
  historical data rather than reacting to a new event type.

## Sources

- https://gamerant.com/elite-dangerous-best-locations-farm-materials/
- https://inara.cz/elite/logbook/72929/
- https://inara.cz/elite/logbook/73614/
- https://steamcommunity.com/app/359320/discussions/0/595152662749522086/
