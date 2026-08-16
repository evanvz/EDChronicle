# Combat Voice Callout Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Combat tab's voice callouts firing on every scanned ship — only speak for genuine "worth acting on" contacts (Hostile/Enemy/PowerPlay-rival, or top-rank ships in a PP- or BGS-relevant system), and never for a ship that's ours.

**Architecture:** A new shared pure-function gate (`_callout_reason()`, `edc/core/event_engine.py`) decides *whether* any voice callout should fire at all; both existing voice paths (the main readout in `_tts_router`, the short quip in `_handle_combat_quip`) call it as a precondition before their existing wording logic runs. A new `"Enemy"` field on `combat_contacts` gives the quip system's `ReceiveText` path (which only has a stored contact, not a raw event) everything the gate needs.

**Tech Stack:** Python, pytest with the established `EventEngine(GameState(), tmp_path)` + `engine.process(event)` write-path pattern (see `tests/test_engage_risk.py`), no Qt needed for Task 1.

## Global Constraints

- `_callout_reason()` never fires for a ship that's ours (our pledged PowerPlay power, or our squadron-aligned faction) — checked first, before any other rule, regardless of category.
- Two categories only: `"enemy"` (Hostile/Enemy LegalStatus, or a PP-rival ship while we hold PP stake here) and `"high_value"` (top-3 rank tier — Dangerous/Deadly/Elite — AND the system is PP-relevant or our squadron faction is a belligerent in an active BGS War/CivilWar here).
- `CombatPhrases.ship_targeted()`'s own wording logic (pilot/rank/faction/wanted/bounty/engage-risk composition) is unchanged — only the precondition for calling it changes.
- No change to `combat_panel.py`'s row-highlight/color logic, `_engage_risk()`, or the Combat tab's "Engage Risk" column.
- No new cooldown/dedup mechanism — existing `_tts_spoken_ships`/6s cooldown (main readout) and 30s cooldown (quip) are unchanged.
- Spec of record: `docs/superpowers/specs/2026-08-16-combat-callout-gating-design.md`.

---

### Task 1: `_callout_reason()` gate + `Enemy` field + new phrase pool

**Files:**
- Modify: `edc/core/event_engine.py` (new function after `_engage_risk`, currently ending line 85; `combat_contacts` write, currently lines 647-664)
- Modify: `edc/audio/handlers/combat.py` (new phrase pool + static method)
- Test: `tests/test_callout_reason.py` (new)

**Interfaces:**
- Produces: `_callout_reason(hostile: bool, enemy: bool, power: str, faction: str, pledged: str, squadron_faction: str, ctrl: str, system_powers: list, pp_state: str, rank: str, squadron_at_war: bool) -> Optional[str]` — returns `"enemy"`, `"high_value"`, or `None`.
- Produces: `combat_contacts[key]["Enemy"]: bool` — new key, alongside the existing `"Wanted"`/`"Hostile"` keys.
- Produces: `CombatPhrases.high_value_contact_scan() -> str` and `CombatPhrases.HIGH_VALUE_CONTACT_SCAN: List[str]`.

Task 2 consumes `_callout_reason()`'s exact signature and the new `"Enemy"` combat_contacts field.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_callout_reason.py`:

```python
"""Tests for the combat voice-callout gate -- pure function, no Qt needed.
Matches tests/test_engage_risk.py's structure/imports."""
import pytest

from edc.core.event_engine import EventEngine, _callout_reason
from edc.core.state import GameState
from edc.audio.handlers.combat import CombatPhrases


# --- _callout_reason ---

def test_hostile_is_enemy_unconditional():
    result = _callout_reason(
        hostile=True, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_legal_enemy_is_enemy_unconditional():
    result = _callout_reason(
        hostile=False, enemy=True, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_pp_rival_in_our_space_is_enemy():
    result = _callout_reason(
        hostile=False, enemy=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result == "enemy"


def test_pp_rival_outside_our_space_is_not_enemy():
    # Regression shape matching _engage_risk's own Vargerson case: rival
    # power ship, but we do NOT control/contest this system.
    result = _callout_reason(
        hostile=False, enemy=False, power="A. Lavigny-Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="A. Lavigny-Duval", system_powers=[], pp_state="",
        rank="Novice", squadron_at_war=False,
    )
    assert result is None


def test_top_rank_in_pp_relevant_system_is_high_value():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result == "high_value"


def test_top_rank_with_squadron_at_war_is_high_value():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="Some Other Faction", pledged="",
        squadron_faction="Our Faction", ctrl="", system_powers=[], pp_state="",
        rank="Dangerous", squadron_at_war=True,
    )
    assert result == "high_value"


def test_top_rank_in_irrelevant_system_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result is None


def test_low_rank_in_relevant_system_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Competent", squadron_at_war=False,
    )
    assert result is None


def test_plain_clean_no_signals_is_none():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="",
        squadron_faction="", ctrl="", system_powers=[], pp_state="",
        rank="Harmless", squadron_at_war=False,
    )
    assert result is None


def test_own_power_never_called_out_even_if_hostile():
    # A ship can't really be both "ours" and Hostile in practice, but the
    # own-side exclusion must still win if it somehow were -- checked first,
    # unconditionally, per the design.
    result = _callout_reason(
        hostile=True, enemy=False, power="Aisling Duval", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Aisling Duval", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=False,
    )
    assert result is None


def test_own_squadron_faction_never_called_out():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="Our Faction", pledged="",
        squadron_faction="Our Faction", ctrl="", system_powers=[], pp_state="",
        rank="Elite", squadron_at_war=True,
    )
    assert result is None


def test_contested_pp_state_counts_as_relevant():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=[], pp_state="Contested",
        rank="Deadly", squadron_at_war=False,
    )
    assert result == "high_value"


def test_system_powers_membership_counts_as_relevant():
    result = _callout_reason(
        hostile=False, enemy=False, power="", faction="", pledged="Aisling Duval",
        squadron_faction="", ctrl="Someone Else", system_powers=["Aisling Duval"], pp_state="",
        rank="Deadly", squadron_at_war=False,
    )
    assert result == "high_value"


# --- combat_contacts write path -- confirms "Enemy" lands on combat_contacts ---

@pytest.fixture
def engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _ship_targeted_event(legal_status, pilot="Test Pilot", ship="Vulture"):
    return {
        "event": "ShipTargeted", "TargetLocked": True, "ScanStage": 3,
        "PilotName": pilot, "Ship": ship, "LegalStatus": legal_status,
    }


def test_enemy_legal_status_sets_enemy_field(engine):
    engine.process(_ship_targeted_event("Enemy"))
    contact = next(iter(engine.state.combat_contacts.values()))
    assert contact["Enemy"] is True


def test_clean_legal_status_leaves_enemy_field_false(engine):
    engine.process(_ship_targeted_event("Clean"))
    contact = next(iter(engine.state.combat_contacts.values()))
    assert contact["Enemy"] is False


# --- CombatPhrases.high_value_contact_scan() ---

def test_high_value_contact_scan_returns_nonempty_string():
    text = CombatPhrases.high_value_contact_scan()
    assert isinstance(text, str) and text
    assert text in CombatPhrases.HIGH_VALUE_CONTACT_SCAN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_callout_reason.py -v`
Expected: FAIL — `ImportError: cannot import name '_callout_reason'` (and later, once that's fixed, `AttributeError`/`KeyError` for the `"Enemy"` field and `high_value_contact_scan`).

- [ ] **Step 3: Add `_callout_reason()`**

Re-read `edc/core/event_engine.py` fresh to confirm `_engage_risk()`'s current end line (currently line 85, immediately before two blank lines and `class EventEngine:`), then insert this new function immediately after it (before the blank lines / `class EventEngine:`):

```python
def _callout_reason(
    hostile: bool, enemy: bool, power: str, faction: str,
    pledged: str, squadron_faction: str,
    ctrl: str, system_powers: list, pp_state: str,
    rank: str, squadron_at_war: bool,
) -> str | None:
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

- [ ] **Step 4: Add the `"Enemy"` field to `combat_contacts`**

Re-read `edc/core/event_engine.py` around the `combat_contacts` write (currently lines 647-664) fresh, then change:

```python
                self.state.combat_contacts[key] = {
                    "Pilot": pilot,
                    "Rank": rank_name,
                    "Ship": ship,
                    "Faction": faction,
                    "Power": target_power,
                    "Wanted": bool(is_wanted),
                    "Hostile": bool(is_hostile),
                    "Bounty": bounty if isinstance(bounty, int) else None,
                    "EngageRisk": _engage_risk(
```

to:

```python
                self.state.combat_contacts[key] = {
                    "Pilot": pilot,
                    "Rank": rank_name,
                    "Ship": ship,
                    "Faction": faction,
                    "Power": target_power,
                    "Wanted": bool(is_wanted),
                    "Hostile": bool(is_hostile),
                    "Enemy": bool(is_enemy_status),
                    "Bounty": bounty if isinstance(bounty, int) else None,
                    "EngageRisk": _engage_risk(
```

(`is_enemy_status` is already computed a few lines above this block, currently line 613 — no new local needed, just reference it.)

- [ ] **Step 5: Add the new phrase pool**

Re-read `edc/audio/handlers/combat.py` fresh, then add this immediately after the existing `POWERPLAY_ENEMY_SCAN` list (currently lines 60-66):

```python
    HIGH_VALUE_CONTACT_SCAN = [
        "Notable contact, Commander. Worth your attention.",
        "High-threat signature detected. Stay sharp.",
        "That one's dangerous. Your call, Commander.",
        "Elite-rated contact in the area. Proceed with caution.",
        "Combat-capable target nearby. Handle as needed.",
    ]
```

and add this new static method immediately after the existing `powerplay_enemy_scan()` method:

```python
    @staticmethod
    def high_value_contact_scan() -> str:
        return pick(CombatPhrases.HIGH_VALUE_CONTACT_SCAN)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_callout_reason.py tests/test_engage_risk.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add edc/core/event_engine.py edc/audio/handlers/combat.py tests/test_callout_reason.py
git commit -m "feat: add combat voice-callout relevance gate and high-value phrase pool"
```

---

### Task 2: Wire both voice paths through the gate

**Files:**
- Modify: `edc/ui/main_window.py` (imports; `_tts_router`'s `ShipTargeted` branch, currently lines 2562-2617; `_handle_combat_quip`, currently lines 3130-3202)

**Interfaces:**
- Consumes: `_callout_reason(hostile, enemy, power, faction, pledged, squadron_faction, ctrl, system_powers, pp_state, rank, squadron_at_war) -> str | None` (Task 1, `edc/core/event_engine.py`).
- Consumes: `combat_contacts[key]["Enemy"]: bool` (Task 1).
- Consumes: `CombatPhrases.high_value_contact_scan() -> str` (Task 1).
- Produces: nothing new — this task is the plan's terminal interface.

This task has no automated test — this TTS-routing pipeline has none in `main_window.py` today, matching this codebase's established convention. Verification is a static syntax check, the full test suite, and a manual live-verification step in-game at the end.

- [ ] **Step 1: Re-read `main_window.py` fresh and update imports**

Re-read `edc/ui/main_window.py` around lines 30-85 fresh (this file is on the project's frequently-stale list — always re-read before editing) to confirm current line numbers, then change:

```python
from edc.core.event_engine import EventEngine, _engage_risk
```

to:

```python
from edc.core.event_engine import EventEngine, _engage_risk, _callout_reason
```

and change:

```python
from edc.core.bgs_conflicts import squadron_faction_name
```

to:

```python
from edc.core.bgs_conflicts import squadron_faction_name, find_squadron_war_enemy
```

- [ ] **Step 2: Gate the main readout (`_tts_router`'s `ShipTargeted` branch)**

Re-read this branch (currently lines 2562-2617) fresh, then change:

```python
            if event_type == "ShipTargeted":
                if not evt.get("TargetLocked"):
                    return ""
                if int(evt.get("ScanStage", 0) or 0) < 3:
                    return ""

                rank         = str(evt.get("PilotRank") or "").strip()
                legal_status = str(evt.get("LegalStatus") or "").strip()
                wanted       = legal_status.lower() == "wanted"
                hostile      = legal_status.lower() == "hostile"
                legal_enemy  = legal_status.lower() == "enemy"
                bounty       = int(evt.get("Bounty") or 0)
                power        = (evt.get("Power") or "").strip()
                faction      = (evt.get("Faction") or "").strip().lower()
                is_friendly  = bool(pledged and power and power.lower() == pledged.lower())
                top_rank     = rank.lower() in ("dangerous", "deadly", "elite")

                # Never call out law enforcement or our own power's ships
                if "internal security" in faction or "security service" in faction:
                    return ""
                if is_friendly:
                    return ""

                ctrl          = (getattr(state, "system_controlling_power", None) or "").strip()
                system_powers = [p.strip() for p in (getattr(state, "system_powers", []) or [])]
                we_control    = bool(pledged and ctrl and ctrl.lower() == pledged.lower())
                we_present    = bool(pledged and any(p.lower() == pledged.lower() for p in system_powers))
                we_active     = we_control or we_present

                power_lower = power.lower() if power else ""
                ship_in_ctrl   = bool(ctrl and power_lower and power_lower == ctrl.lower())
                ship_in_powers = bool(power and any(p.lower() == power_lower for p in system_powers))
                ship_active    = ship_in_ctrl or ship_in_powers

                is_enemy      = bool(we_active and power and ship_active)
                is_high_value = bool((not is_enemy) and wanted and bounty > 500_000 and top_rank)

                engage_risk = _engage_risk(
                    wanted, hostile, power, pledged, ctrl,
                    getattr(state, "system_government", None),
                    enemy=legal_enemy,
                )

                pilot = evt.get("PilotName_Localised") or evt.get("PilotName") or ""
                ship  = evt.get("Ship_Localised") or evt.get("Ship") or ""
                key   = f"{pilot}|{ship}"
                if key in self._tts_spoken_ships:
                    return ""
                now = time.monotonic()
                if now < self._tts_ship_cooldown_until:
                    return ""
                self._tts_spoken_ships.add(key)
                self._tts_ship_cooldown_until = now + 6.0
                return CombatPhrases.ship_targeted(
                    ship, rank, power, is_enemy, wanted, bounty, is_high_value, engage_risk
                )
```

to:

```python
            if event_type == "ShipTargeted":
                if not evt.get("TargetLocked"):
                    return ""
                if int(evt.get("ScanStage", 0) or 0) < 3:
                    return ""

                rank         = str(evt.get("PilotRank") or "").strip()
                legal_status = str(evt.get("LegalStatus") or "").strip()
                wanted       = legal_status.lower() == "wanted"
                hostile      = legal_status.lower() == "hostile"
                legal_enemy  = legal_status.lower() == "enemy"
                bounty       = int(evt.get("Bounty") or 0)
                power        = (evt.get("Power") or "").strip()
                faction_raw  = evt.get("Faction") or ""
                faction      = faction_raw.strip().lower()
                is_friendly  = bool(pledged and power and power.lower() == pledged.lower())
                top_rank     = rank.lower() in ("dangerous", "deadly", "elite")

                # Never call out law enforcement or our own power's ships
                if "internal security" in faction or "security service" in faction:
                    return ""
                if is_friendly:
                    return ""

                ctrl          = (getattr(state, "system_controlling_power", None) or "").strip()
                system_powers = [p.strip() for p in (getattr(state, "system_powers", []) or [])]
                pp_state      = getattr(state, "system_powerplay_state", None)
                we_control    = bool(pledged and ctrl and ctrl.lower() == pledged.lower())
                we_present    = bool(pledged and any(p.lower() == pledged.lower() for p in system_powers))
                we_active     = we_control or we_present

                power_lower = power.lower() if power else ""
                ship_in_ctrl   = bool(ctrl and power_lower and power_lower == ctrl.lower())
                ship_in_powers = bool(power and any(p.lower() == power_lower for p in system_powers))
                ship_active    = ship_in_ctrl or ship_in_powers

                is_enemy      = bool(we_active and power and ship_active)
                is_high_value = bool((not is_enemy) and wanted and bounty > 500_000 and top_rank)

                squadron_faction = squadron_faction_name(getattr(state, "factions", None))
                squadron_at_war  = bool(find_squadron_war_enemy(
                    getattr(state, "factions", None), getattr(state, "system_conflicts", None)
                ))
                callout_reason = _callout_reason(
                    hostile, legal_enemy, power, faction_raw, pledged, squadron_faction,
                    ctrl, system_powers, pp_state, rank, squadron_at_war,
                )
                if callout_reason is None:
                    return ""

                engage_risk = _engage_risk(
                    wanted, hostile, power, pledged, ctrl,
                    getattr(state, "system_government", None),
                    enemy=legal_enemy,
                )

                pilot = evt.get("PilotName_Localised") or evt.get("PilotName") or ""
                ship  = evt.get("Ship_Localised") or evt.get("Ship") or ""
                key   = f"{pilot}|{ship}"
                if key in self._tts_spoken_ships:
                    return ""
                now = time.monotonic()
                if now < self._tts_ship_cooldown_until:
                    return ""
                self._tts_spoken_ships.add(key)
                self._tts_ship_cooldown_until = now + 6.0
                return CombatPhrases.ship_targeted(
                    ship, rank, power, is_enemy, wanted, bounty, is_high_value, engage_risk
                )
```

(`faction_raw` is added because `_callout_reason()`'s `faction`/`squadron_faction` comparison must be case-sensitive-exact against `squadron_faction_name()`'s return value — the pre-existing `faction` local is lowercased for the "internal security" substring check just above, which would break an exact-match comparison; `faction_raw` preserves the original casing for the gate call while `faction`/`faction_lower` stays as-is for the existing substring check. `is_enemy`/`is_high_value` — the PP-territory-inference locals already computed here — are left untouched and still feed `CombatPhrases.ship_targeted()`'s wording exactly as before; only the new `callout_reason` precondition is added, nothing about the existing wording computation changes.)

- [ ] **Step 3: Rework `_handle_combat_quip`**

Re-read this method (currently lines 3130-3202) fresh, then replace it entirely with:

```python
    def _handle_combat_quip(self, event_type: str, evt: dict):
        if not getattr(self.cfg, "tts_enabled", False):
            return
        now = time.monotonic()
        if now < self._commander_quip_cooldown_until:
            return

        pledged = (getattr(self.state, "pp_power", None) or "").strip()
        ctrl    = (getattr(self.state, "system_controlling_power", None) or "").strip()
        system_powers = [p.strip() for p in (getattr(self.state, "system_powers", []) or [])]
        pp_state = getattr(self.state, "system_powerplay_state", None)
        squadron_faction = squadron_faction_name(getattr(self.state, "factions", None))
        squadron_at_war  = bool(find_squadron_war_enemy(
            getattr(self.state, "factions", None), getattr(self.state, "system_conflicts", None)
        ))

        def _wording(wanted: bool, bounty, power: str) -> str:
            """Picks which phrase pool fits, once _callout_reason() has
            already decided a quip is warranted at all -- presentation
            only, not a gating decision."""
            if wanted and isinstance(bounty, int) and bounty >= 500_000:
                return CombatPhrases.wanted_target_scan()
            if pledged and power and power.strip().lower() != pledged.strip().lower():
                return CombatPhrases.powerplay_enemy_scan()
            return CombatPhrases.high_value_contact_scan()

        quip = ""
        if event_type == "ReceiveText":
            from_raw = evt.get("From") or ""
            if "$npc_name_decorate" not in from_raw:
                return
            # Parse pilot name from "$npc_name_decorate:#name=X;"
            pilot_name = ""
            if "#name=" in from_raw:
                pilot_name = from_raw.split("#name=", 1)[1].rstrip(";").strip()
            if not pilot_name:
                return
            contacts = getattr(self.state, "combat_contacts", {}) or {}
            contact = next(
                (c for c in contacts.values()
                 if isinstance(c, dict) and c.get("Pilot") == pilot_name),
                None,
            )
            if not contact:
                return
            reason = _callout_reason(
                bool(contact.get("Hostile")), bool(contact.get("Enemy")),
                contact.get("Power", ""), contact.get("Faction", ""),
                pledged, squadron_faction, ctrl, system_powers, pp_state,
                contact.get("Rank", ""), squadron_at_war,
            )
            if reason is not None:
                quip = CombatPhrases.npc_challenge()
        elif event_type == "ShipTargeted":
            if not evt.get("TargetLocked") or int(evt.get("ScanStage", 0) or 0) < 3:
                return
            power  = (evt.get("Power") or "").strip()
            legal  = str(evt.get("LegalStatus") or "").strip().lower()
            wanted = legal == "wanted"
            hostile = legal == "hostile"
            legal_enemy = legal == "enemy"
            bounty = evt.get("Bounty")
            faction = evt.get("Faction") or ""
            rank   = str(evt.get("PilotRank") or "").strip()
            reason = _callout_reason(
                hostile, legal_enemy, power, faction, pledged, squadron_faction,
                ctrl, system_powers, pp_state, rank, squadron_at_war,
            )
            if reason is not None:
                quip = _wording(wanted, bounty, power)

        if not quip:
            return
        self._commander_quip_cooldown_until = now + 30.0
        if event_type == "ReceiveText":
            QTimer.singleShot(2000, lambda q=quip: self.tts.speak(q, priority=3))
        else:
            self.tts.speak(quip, priority=3)
```

- [ ] **Step 4: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Manual live verification**

Launch the app, go into a combat-relevant system in-game, target several ships. Confirm:
- A plain-Clean, low-rank NPC (e.g. Novice/Competent, no bounty, not PP-relevant) gets **no** voice callout at all.
- A Hostile or LegalStatus-Enemy ship still gets a callout.
- A Dangerous/Deadly/Elite-rank ship gets a callout when the system is PP-relevant (you hold PP stake) or a BGS War/CivilWar involving your squadron faction is active here.
- The same top-rank ship does **not** get a callout in an unrelated system with no PP/BGS relevance.
- A Wanted, high-bounty ship belonging to your own pledged PowerPlay power, or your own squadron-aligned faction, gets **no** callout.
- The short commander-quip line (separate from the full readout) follows the same relevance rules.
- No crash/traceback in the console during any of the above.

- [ ] **Step 7: Commit**

```bash
git add edc/ui/main_window.py
git commit -m "feat: gate combat voice callouts to enemy and high-value contacts only"
```
