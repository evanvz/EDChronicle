# Engage Risk Indicator — Design

## Context

The Combat tab's contacts table (`edc/ui/panels/combat_panel.py`) shows raw
per-contact flags (Power, Enemy, Wanted, Bounty, Last Seen) but never
answers the question the user actually needs before pulling the trigger:
**will killing this specific ship put a bounty on me?** That's a different
question from "is this ship bounty-eligible" or "is it flagged Enemy" —
confirmed today against two real, opposite cases in the same play session:

- **Bibari** (player's own pledged PowerPlay territory): rival-power ships,
  `LegalStatus: "Enemy"`. Confirmed via journal: killing them produced
  PowerPlay merit gains, no `CommitCrime`, no bounty. Safe.
- **Vargerson** (territory controlled by a different power): ordinary
  `LegalStatus: "Clean"` local-faction ships, no PowerPlay relevance at
  all. Per real game mechanics, killing a Clean ship outside Anarchy
  space is a crime and puts a bounty on the player. Not safe.

## What's already built, and one significant existing-but-unused signal

`edc/ui/main_window.py`'s `_handle_combat_quip`/`_qualifies` (commit
`0fef744`, shipped earlier today) already distinguishes the Bibari-style
case for the purpose of a voice quip — `pp_enemy` (rival power encountered
in the player's own controlled territory). That logic is reused, not
duplicated, by this design.

Separately, `edc/core/event_engine.py:571-579` — discovered while
investigating this feature, predates today's work — already parses and
stores a **`Hostile`** flag on every `combat_contacts` entry
(`LegalStatus == "hostile"`), with an existing code comment stating (with
specific, confident justification) that a Hostile-flagged ship is already
attacking the player and killing it back carries **no bounty/notoriety
consequence, unconditionally** — stronger than the PP-territory case,
since it holds regardless of PowerPlay/Conflict-Zone context. This flag
is captured into the data model but **never rendered anywhere** — no
table column, no voice callout. This design surfaces it for the first
time rather than re-deriving the claim (it predates this session and
its rationale is already recorded in that comment).

External verification done before designing further (do not re-derive):
Anarchy-controlled systems genuinely exempt the player from bounty/fine/
reputation consequences for any kill — **except** within roughly 1000km
(space) / 200km (surface) of a station or settlement owned by a
non-anarchy faction inside that system, which plays by its own owner's
rules. The app has no way to detect proximity to such a pocket today, so
Anarchy cannot be collapsed into a flat "Safe" — it gets its own tier.
`LegalStatus`'s full enum could not be authoritatively confirmed via
external community schema docs (incomplete/inconsistent); this design
relies only on the four values with real confirmation: `Clean`, `Wanted`,
`Enemy` (real journal data, today), `Hostile` (existing code comment,
specific and confident).

## Design

### Confidence tiers → three-state verdict

User confirmed: **Safe / Caution / Unknown**, not a binary Safe/Not-Safe
(a binary would misrepresent the Anarchy caveat as certain in either
direction).

- **Safe**: `Wanted`, OR `Hostile`, OR (`Enemy`-equivalent power mismatch
  AND the player is in their own controlled PowerPlay territory — the
  existing `pp_enemy`/`in_my_pp_space` condition, reused unchanged).
- **Caution**: current system's government is Anarchy (and none of the
  Safe conditions already matched).
- **Unknown**: everything else (plain Clean, or a power mismatch outside
  the player's own territory) — presented as "will likely draw a bounty,"
  matching real default crime mechanics, not a neutral shrug.

### New shared function — `_engage_risk()`

A new, pure, standalone function (module-level in `edc/core/event_engine.py`,
alongside the existing `Hostile`-parsing code it extends) so both the
data-model write path (combat_contacts) and the voice path can call the
identical logic — no duplicated risk rules:

```python
def _engage_risk(wanted: bool, hostile: bool, power: str, pledged: str,
                  ctrl: str, government: str) -> str:
    """
    Returns "safe", "caution", or "unknown" -- whether killing a contact
    with these attributes is expected to draw a bounty against the
    player. Deliberately conservative: anything not confidently known
    safe defaults to "unknown", never a false "safe".
    """
    if wanted or hostile:
        return "safe"
    p = (pledged or "").strip().lower()
    in_my_pp_space = bool(p and ctrl and ctrl.strip().lower() == p)
    pp_enemy = bool(p and power and power.strip().lower() != p)
    if in_my_pp_space and pp_enemy:
        return "safe"
    if "anarchy" in (government or "").lower():
        return "caution"
    return "unknown"
```

This does not touch or refactor `_qualifies()` in `main_window.py` —
that function answers a different question (is this worth a commander
quip at all) and stays as-is; `_engage_risk()` is additive, not a
replacement.

### Data model — `combat_contacts` gains an `EngageRisk` field

`edc/core/event_engine.py`'s existing `combat_contacts[key] = {...}`
write (the same block that already computes `Wanted`/`Hostile`) gains one
more computed field: `"EngageRisk": _engage_risk(is_wanted, is_hostile,
target_power, self.state.pp_power, self.state.system_controlling_power,
self.state.system_government)`. Computed once, at write time, alongside
the fields it depends on — no new read-time computation needed anywhere
else.

### UI — new Combat tab column

`edc/ui/panels/combat_panel.py`'s contacts table gains a new column,
"Engage Risk", reading `rec.get("EngageRisk")` and rendering with the
same color-coded badge convention already used for `is_high_bounty` in
this file (found at combat_panel.py:377-411) — green/"Safe", yellow/
"Caution", and the existing muted/warning color already used for
low-confidence rows for "Unknown". Placed as its own column (not merged
into the existing Enemy column, since that answers "what is this ship"
and this answers "is it safe to shoot" — two different questions, both
useful separately).

### Voice — extends the existing `ship_targeted()` assessment

Per the reliability requirement (a cooldown-gated system risked going
silent right after an unrelated quip), this rides the **always-spoken**
path, not the commander-quip system. `CombatPhrases.ship_targeted()`
(`edc/audio/handlers/combat.py`) gains a new `engage_risk: str` parameter,
appending one of three short clauses to its existing composed sentence
(after the existing wanted/bounty clause): "Clear to engage." (safe),
"Caution — anarchy space, not guaranteed near a port." (caution), or
"Engaging will likely draw a bounty." (unknown). `main_window.py`'s
`_tts_router` (the `ShipTargeted` branch, ~line 2528-2582) already
computes every input `_engage_risk()` needs (`pledged`, `ctrl`, `wanted`,
`power`) in that same block — adds one call and threads the result
through to the existing `CombatPhrases.ship_targeted(...)` call.

## Testing

- `_engage_risk()`: pure-function unit tests (no Qt) — each of the four
  Safe-condition branches individually (wanted, hostile, pp_enemy+in-my-
  territory), the Anarchy caution case, and the default unknown case,
  plus confirming a pp_enemy match OUTSIDE the player's own territory
  does NOT return safe (this is the exact Vargerson-shaped case that
  must not be misclassified).
- `combat_contacts` write path: extend existing event-handling tests (or
  add new ones matching this repo's established `Database`/`Repository`-
  free unit-test style for `event_engine.py`, if one exists — check
  before inventing a new pattern) confirming `EngageRisk` lands correctly
  on a constructed contact record for each tier.
- `CombatPhrases.ship_targeted()`: direct unit test confirming each of
  the three `engage_risk` values produces the expected appended clause.
- Combat tab table rendering and the live TTS clause: no automated test,
  matches this codebase's established convention for panel-rendering and
  voice-line wiring — verified live.

## Out of scope

- Refactoring `_qualifies()`/the commander-quip system to reuse
  `_engage_risk()` — different question, left alone.
- Detecting proximity to a non-anarchy-owned station/settlement inside
  an Anarchy system (would upgrade Caution to a confirmed Safe/Unsafe in
  that specific radius) — not tracked today, no journal signal currently
  captured for it, separate future feature if ever pursued.
- Conflict Zone side-selection tracking as its own signal — `Hostile`
  already covers the actual in-combat-with-you case, which is the
  practically relevant one; a broader "is this the CZ's opposing side"
  signal beyond that is not built here.
