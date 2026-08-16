# Combat Voice Callout Gating — Design

## Context

The Combat tab's voice notifications currently fire on every successfully
scanned ship (`ShipTargeted`, `ScanStage >= 3`), not just ones worth acting
on — confirmed via direct code read, root-caused to a change made earlier
this session while building the Engage Risk Indicator feature: the
`_tts_router()` `ShipTargeted` branch's early `else: return ""` gate
(`edc/ui/main_window.py`, currently lines 2562-2617) was deliberately
removed so the engage-risk clause would be spoken even for previously-silent
Hostile/low-bounty-Wanted/plain-Clean contacts. That fixed one bug
(silenced engage-risk callouts) but introduced this one (every ship now
gets a full voice readout).

Two independent voice paths exist for `ShipTargeted`, both touched this
session:

1. **Main readout** — `_tts_router()`'s `ShipTargeted` branch. Speaks the
   full `CombatPhrases.ship_targeted(...)` line (pilot/rank/faction/wanted/
   bounty/engage-risk). Currently ungated (the bug).
2. **Commander quip** — `_handle_combat_quip()` (currently lines
   3130-3202), a separate short flavor-line system ("Bounty confirmed,
   permission to engage?" / "Rival power vessel..."), already gated by a
   nested `_qualifies()` closure that only recognizes two cases: a
   Wanted+bounty≥500k+top-rank target ("bounty"), or a PowerPlay-rival ship
   while we hold PP stake here ("pp_enemy"). This system was not broken by
   the Engage Risk change, but its gate is narrower than what's now wanted
   and needs to grow.

A third, related system already exists in `edc/core/event_engine.py`'s
`ShipTargeted` handler (currently lines ~695-757): text-alert construction
(`state.current_contact_alert`, `state.pp_enemy_alerts`, `msgs.append(alert)`)
with gating logic very close to what's wanted here (Hostile always-alert;
PP-space bounty/PP-enemy; elsewhere bounty+rank). **This system is
currently dead** — its one UI consumer
(`main_window.py`'s Overview HUD assembly, ~line 3883) iterates
`pp_enemy_alerts` expecting each entry to be a `dict` with a `"msg"` key,
but the producer stores plain strings (`self.state.pp_enemy_alerts = [alert]`
where `alert` is a `str`) — every entry fails the `isinstance(alert, dict)`
check and is silently skipped. Nothing renders from it. This design does
not fix that dead code path (out of scope, no user-visible effect either
way) but reuses its proven rule *structure* as the starting point for the
new shared gate, since it already handles the Hostile/PP-space/bounty-target
trichotomy well.

## Design

### The shared gate

New module-level pure function in `edc/core/event_engine.py`, placed near
the existing `_engage_risk()` (same file, same style — pre-derived
booleans/strings in, no raw event dicts):

```python
def _callout_reason(
    hostile: bool, enemy: bool, power: str, faction: str,
    pledged: str, squadron_faction: str,
    ctrl: str, system_powers: list, pp_state: str,
    rank: str, squadron_at_war: bool,
) -> Optional[str]:
    """
    Returns "enemy", "high_value", or None -- whether a scanned contact is
    worth a voice callout at all (any callout, not which words to use).

    Two independent categories:
      - "enemy": LegalStatus Hostile or Enemy (unconditional -- the game
        has already decided this is fair game), or a rival PowerPlay
        power's ship while we hold PP stake in this system (control it,
        are one of the contesting powers, or it's Contested).
      - "high_value": top-3 combat rank tier (Dangerous/Deadly/Elite), AND
        the system is relevant to us -- either the PP-stake condition
        above, or our squadron-aligned faction is a belligerent in an
        active BGS War/CivilWar here (squadron_at_war=True). Rank alone
        does not qualify outside a relevant system.

    Never fires for a ship that's ours -- our pledged PowerPlay power, or
    our squadron-aligned faction -- regardless of category, checked first:
    we don't shoot our own.
    """
    power_l = (power or "").strip().lower()
    pledged_l = (pledged or "").strip().lower()
    is_own_power = bool(pledged_l and power_l and power_l == pledged_l)
    is_own_faction = bool(squadron_faction and faction and faction == squadron_faction)
    if is_own_power or is_own_faction:
        return None

    if hostile or enemy:
        return "enemy"

    in_my_pp_space = bool(pledged_l and (
        (ctrl or "").strip().lower() == pledged_l
        or pledged_l in [p.strip().lower() for p in (system_powers or [])]
        or (pp_state or "").strip().lower() == "contested"
    ))
    pp_enemy = bool(pledged_l and power_l and power_l != pledged_l)
    if in_my_pp_space and pp_enemy:
        return "enemy"

    top_rank = rank.strip().lower() in ("dangerous", "deadly", "elite")
    if top_rank and (in_my_pp_space or squadron_at_war):
        return "high_value"

    return None
```

`squadron_at_war` is computed by each caller via the already-existing
`find_squadron_war_enemy(factions, system_conflicts)` (`edc/core/bgs_conflicts.py`)
— `bool(...)` of its result. This asks "is our squadron faction fighting
*anyone* here," not "is *this specific contact's* faction the one we're
fighting" — a Dangerous-rank NPC of any faction in a warzone our squadron
is party to counts as relevant.

### `combat_contacts` gains an `"Enemy"` field

`edc/core/event_engine.py`'s `ShipTargeted` handler already computes
`is_enemy_status` (`LegalStatus == "enemy"`) for `_engage_risk()`'s `enemy=`
argument, but never stores it. Add it to the `combat_contacts` write
(currently lines 647-664, alongside the existing `"Wanted"`/`"Hostile"`
keys): `"Enemy": bool(is_enemy_status)`. Needed so `_handle_combat_quip`'s
`ReceiveText` branch — which only has a previously-stored contact dict, not
the raw `ShipTargeted` event — has everything `_callout_reason()` needs.

### Both voice paths call the shared gate as a precondition

**Main readout** (`_tts_router`'s `ShipTargeted` branch): compute
`reason = _callout_reason(...)` using the branch's already-derived
`hostile`, `legal_enemy`, `power`, `faction`, `pledged`, `ctrl`,
`system_powers`, `rank`, plus two new lookups —
`squadron_faction_name(state.factions)` and
`bool(find_squadron_war_enemy(state.factions, state.system_conflicts))`
— and a `pp_state = getattr(state, "system_powerplay_state", None)` this
branch doesn't currently read. `return ""` if `reason is None`. If
non-`None`, proceed exactly as today — `CombatPhrases.ship_targeted(...)`'s
own wanted/bounty/engage-risk wording logic is untouched, only *whether*
to speak changes, not *what* gets said when it does.

**Commander quip** (`_handle_combat_quip`): the nested `_qualifies()`
closure is replaced by a call to the shared `_callout_reason()`. Its
`ReceiveText` branch reads `contact.get("Enemy")` (new field) alongside
the existing `contact.get("Hostile")`/`contact.get("Wanted")`. Its
`ShipTargeted` branch gains `hostile`/`legal_enemy` locals (not currently
computed there) alongside its existing `wanted`/`bounty`/`power`/`rank`.
If the gate returns `None`, no quip — same as before. If non-`None`, a
**wording sub-check** (new, presentation-only, not a gating decision)
picks which phrase pool fits:

```python
if wanted and isinstance(bounty, int) and bounty >= 500_000:
    quip = CombatPhrases.wanted_target_scan()
elif pledged and power and power.strip().lower() != pledged.strip().lower():
    quip = CombatPhrases.powerplay_enemy_scan()
else:
    quip = CombatPhrases.high_value_contact_scan()
```

### New phrase pool

`edc/audio/handlers/combat.py`'s `CombatPhrases` gains a third short pool
alongside `WANTED_TARGET_SCAN`/`POWERPLAY_ENEMY_SCAN`, for cases the gate
allows through that don't fit either existing wording (a Hostile contact
unrelated to PowerPlay — e.g. a BGS Conflict Zone combatant — or a Clean
top-rank "high value" ship with no bounty at all):

```python
    HIGH_VALUE_CONTACT_SCAN = [
        "Notable contact, Commander. Worth your attention.",
        "High-threat signature detected. Stay sharp.",
        "That one's dangerous. Your call, Commander.",
        "Elite-rated contact in the area. Proceed with caution.",
        "Combat-capable target nearby. Handle as needed.",
    ]

    @staticmethod
    def high_value_contact_scan() -> str:
        return pick(CombatPhrases.HIGH_VALUE_CONTACT_SCAN)
```

## Out of scope

- No change to `CombatPhrases.ship_targeted()`'s own wording logic (pilot/
  rank/faction/wanted/bounty/engage-risk composition) — only the
  precondition for calling it changes.
- No change to `combat_panel.py`'s row-highlight/color logic — it already
  independently computes its own `is_hostile`/`is_enemy`/
  `bgs_war_faction_match`/`is_high_bounty` for visual purposes and stays
  as-is; this design is voice-only.
- No fix to the dead `state.current_contact_alert`/`pp_enemy_alerts` text
  system described in Context — it has no observable effect today either
  way, and fixing it is a separate, unrelated concern from what was asked.
- No change to `_engage_risk()` or the Combat tab's "Engage Risk" column —
  those already work correctly and are unrelated to whether a voice
  callout fires.
- No new cooldown/dedup mechanism — the existing per-ship dedup
  (`_tts_spoken_ships`) and cooldowns (6s main readout, 30s quip) are
  unchanged; this design only narrows *which* contacts reach them.
