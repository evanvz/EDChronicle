# Engage Risk Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Combat tab and the target-scan voice line an explicit Safe/Caution/Unknown verdict for "will killing this contact put a bounty on me" — a question distinct from "is this ship bounty-eligible" that the app currently never answers directly.

**Architecture:** A new pure function `_engage_risk()` in `edc/core/event_engine.py` computes the verdict once, at the point `combat_contacts` entries are already being built (reusing already-tracked `Wanted`/`Hostile` flags plus PowerPlay-territory and Anarchy-government checks). The Combat tab reads the stored verdict into a new table column. The voice assessment (`CombatPhrases.ship_targeted()`) gains the same verdict as a spoken clause, and the branch that currently silences most contacts before ever reaching that phrase is loosened so the clause is actually heard for the cases that matter.

**Tech Stack:** Python 3, PyQt6, pytest.

## Global Constraints

- Do not modify `_qualifies()`/the commander-quip system in `edc/ui/main_window.py` — untouched, answers a different question (is this worth a quip, not is it safe).
- Do not touch the existing row-background priority chain in `combat_panel.py` (destroyed → current → hostile → pp-enemy → high-bounty → wanted → war-faction) — only add the new column and its own independent per-cell foreground color.
- Do not add Conflict-Zone-side tracking or station/settlement-proximity detection — explicitly out of scope.
- The existing "never call out law enforcement or our own power's ships" silence in the `ShipTargeted` voice branch must be preserved exactly — only the LATER unconditional `else: return ""` (which currently silences plain/Hostile/low-bounty-wanted contacts) is removed.
- The existing `_tts_spoken_ships` dedup and `_tts_ship_cooldown_until` 6-second cooldown must still apply — this change makes MORE contacts reach that gate, not bypass it.

---

### Task 1: `_engage_risk()` backend logic and phrase composition

**Files:**
- Modify: `edc/core/event_engine.py`
- Modify: `edc/audio/handlers/combat.py`
- Test: `tests/test_engage_risk.py` (new)

**Interfaces:**
- Consumes: nothing from other tasks (this task is standalone).
- Produces: `_engage_risk(wanted: bool, hostile: bool, power: str, pledged: str, ctrl: str, government: str) -> str` (module-level, `edc/core/event_engine.py`) returning `"safe"`/`"caution"`/`"unknown"`; `combat_contacts` entries gain an `"EngageRisk"` key; `CombatPhrases.ship_targeted()` gains a new `engage_risk: str = ""` parameter. Task 2 imports `_engage_risk` and reads `"EngageRisk"`/calls `ship_targeted()` with the new parameter.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engage_risk.py`:

```python
"""Tests for the combat engage-risk verdict -- pure functions, no Qt
needed."""
from edc.core.event_engine import _engage_risk
from edc.audio.handlers.combat import CombatPhrases


# --- _engage_risk ---

def test_wanted_is_safe():
    assert _engage_risk(True, False, "", "", "", "") == "safe"


def test_hostile_is_safe():
    assert _engage_risk(False, True, "", "", "", "") == "safe"


def test_pp_enemy_in_my_own_territory_is_safe():
    # Rival power ship encountered while I control this system myself.
    result = _engage_risk(
        wanted=False, hostile=False, power="A. Lavigny-Duval",
        pledged="Aisling Duval", ctrl="Aisling Duval", government="Patronage",
    )
    assert result == "safe"


def test_pp_enemy_outside_my_own_territory_is_not_safe():
    # Regression test for the exact Vargerson case: rival power ship, but
    # I do NOT control this system (someone else does) -- must NOT be
    # misclassified as safe just because the powers differ.
    result = _engage_risk(
        wanted=False, hostile=False, power="Aisling Duval",
        pledged="Aisling Duval", ctrl="A. Lavigny-Duval", government="Confederacy",
    )
    assert result == "unknown"


def test_anarchy_government_is_caution():
    result = _engage_risk(
        wanted=False, hostile=False, power="", pledged="", ctrl="", government="Anarchy",
    )
    assert result == "caution"


def test_plain_clean_no_signals_is_unknown():
    assert _engage_risk(False, False, "", "", "", "") == "unknown"


def test_safe_conditions_checked_before_anarchy():
    # A Wanted target in an Anarchy system is still unconditionally safe
    # (lawful bounty hunting), not merely "caution".
    result = _engage_risk(
        wanted=True, hostile=False, power="", pledged="", ctrl="", government="Anarchy",
    )
    assert result == "safe"


# --- CombatPhrases.ship_targeted() engage_risk clause ---

def test_ship_targeted_appends_safe_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="safe",
    )
    assert text.endswith("Clear to engage.")


def test_ship_targeted_appends_caution_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="caution",
    )
    assert text.endswith("Caution -- anarchy space, not guaranteed near a port.")


def test_ship_targeted_appends_unknown_clause():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False, engage_risk="unknown",
    )
    assert text.endswith("Engaging will likely draw a bounty.")


def test_ship_targeted_appends_no_clause_when_risk_not_given():
    text = CombatPhrases.ship_targeted(
        "Vulture", "Competent", "", False, False, 0, False,
    )
    assert text == "Vulture Competent."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_engage_risk.py -v`
Expected: FAIL — `ImportError` on `_engage_risk` (doesn't exist yet), and the `ship_targeted()` calls fail with `TypeError: unexpected keyword argument 'engage_risk'`.

- [ ] **Step 3: Add `_engage_risk()` to `edc/core/event_engine.py`**

Read the file fresh to find a sensible spot for a new module-level function (near other small free functions at the top of the file, not buried mid-file — check the file's current top-level structure before picking the exact line). Add:

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

- [ ] **Step 4: Thread `_engage_risk()` into the `combat_contacts` write**

Read the file fresh around the `ShipTargeted`/`Scan` handler that builds `self.state.combat_contacts[key] = {...}` (search for that exact assignment). Confirm the current dict literal still matches:

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
                    "LastSeen": ts,
                }
```

Add one new key, right after `"Bounty": ...,`:

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
                        is_wanted, is_hostile, target_power,
                        getattr(self.state, "pp_power", None),
                        getattr(self.state, "system_controlling_power", None),
                        getattr(self.state, "system_government", None),
                    ),
                    "LastSeen": ts,
                }
```

- [ ] **Step 5: Add the `engage_risk` parameter to `CombatPhrases.ship_targeted()`**

Read `edc/audio/handlers/combat.py` fresh. Confirm the current `ship_targeted()` body still matches:

```python
    @staticmethod
    def ship_targeted(ship: str, rank: str, power: str, is_enemy: bool,
                      wanted: bool, bounty: int, is_high_value: bool = False) -> str:
        """Compose a full target assessment phrase from available attributes."""
        parts = [ship or "Unknown ship"]
        if rank:
            parts.append(rank + ".")
        if is_enemy and power:
            parts.append(f"{power} faction. Enemy.")
        elif power:
            parts.append(f"{power}.")
        if is_high_value:
            parts.append("High value target.")
        if wanted:
            if bounty:
                parts.append(f"Wanted. Bounty {bounty:,} credits.")
            else:
                parts.append("Wanted.")
        elif bounty:
            parts.append(f"Bounty {bounty:,} credits.")
        return " ".join(parts)
```

Replace with:

```python
    @staticmethod
    def ship_targeted(ship: str, rank: str, power: str, is_enemy: bool,
                      wanted: bool, bounty: int, is_high_value: bool = False,
                      engage_risk: str = "") -> str:
        """Compose a full target assessment phrase from available attributes."""
        parts = [ship or "Unknown ship"]
        if rank:
            parts.append(rank + ".")
        if is_enemy and power:
            parts.append(f"{power} faction. Enemy.")
        elif power:
            parts.append(f"{power}.")
        if is_high_value:
            parts.append("High value target.")
        if wanted:
            if bounty:
                parts.append(f"Wanted. Bounty {bounty:,} credits.")
            else:
                parts.append("Wanted.")
        elif bounty:
            parts.append(f"Bounty {bounty:,} credits.")
        if engage_risk == "safe":
            parts.append("Clear to engage.")
        elif engage_risk == "caution":
            parts.append("Caution -- anarchy space, not guaranteed near a port.")
        elif engage_risk == "unknown":
            parts.append("Engaging will likely draw a bounty.")
        return " ".join(parts)
```

(Confirmed via repo-wide grep: `main_window.py`'s `_tts_router` is the only caller of `ship_targeted()` — the `engage_risk=""` default exists only so this Task 1 commit doesn't break that call site before Task 2 updates it, not because any other caller needs it.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_engage_risk.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass, no regressions.

- [ ] **Step 8: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/core/event_engine.py', encoding='utf-8').read()); ast.parse(open('edc/audio/handlers/combat.py', encoding='utf-8').read()); print('PARSE OK')"`
Expected: `PARSE OK`

- [ ] **Step 9: Commit**

```bash
git add edc/core/event_engine.py edc/audio/handlers/combat.py tests/test_engage_risk.py
git commit -m "feat: add engage-risk verdict (safe/caution/unknown) for combat contacts

New _engage_risk() answers a question the app never answered directly:
will killing THIS contact put a bounty on the player, distinct from
whether the contact itself is bounty-eligible. Confirmed safe: Wanted,
Hostile (already tracked but never surfaced), or a rival-power ship
encountered in the player's own controlled PowerPlay territory.
Anarchy-government systems get their own \"caution\" tier rather than a
false \"safe\" (real exception: not guaranteed near a station/settlement
owned by a different faction). Everything else defaults to \"unknown\",
matching the real default crime consequence. Stored on combat_contacts
and threaded through the voice assessment phrase; Combat tab wiring is
Task 2."
```

---

### Task 2: Combat tab column and voice wiring

**Files:**
- Modify: `edc/ui/panels/combat_panel.py`
- Modify: `edc/ui/main_window.py`

**Interfaces:**
- Consumes: `_engage_risk()` (import from `edc.core.event_engine`), `combat_contacts` entries' `"EngageRisk"` key, `CombatPhrases.ship_targeted(..., engage_risk=...)` — all from Task 1, unchanged.
- Produces: nothing consumed by other tasks (this is the last task).

- [ ] **Step 1: Add the "Engage Risk" column to the contacts table**

Read `edc/ui/panels/combat_panel.py` fresh in full around the table setup (`__init__`) and `refresh()`. Confirm the current header/column-count/resize-mode lines still match:

```python
        self.combat_table = QTableWidget()
        self.combat_table.setColumnCount(9)
        self.combat_table.setHorizontalHeaderLabels([
            "Pilot", "Rank", "Ship", "Faction",
            "Power", "Enemy", "Wanted", "Bounty", "Last Seen"
        ])
```
```python
        for col in [1, 2, 4, 5, 6, 7, 8]:
            self.combat_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
```

Change to:

```python
        self.combat_table = QTableWidget()
        self.combat_table.setColumnCount(10)
        self.combat_table.setHorizontalHeaderLabels([
            "Pilot", "Rank", "Ship", "Faction",
            "Power", "Enemy", "Wanted", "Bounty", "Engage Risk", "Last Seen"
        ])
```
```python
        for col in [1, 2, 4, 5, 6, 7, 8, 9]:
            self.combat_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
```

(New column order: Pilot=0, Rank=1, Ship=2, Faction=3, Power=4, Enemy=5, Wanted=6, Bounty=7, Engage Risk=8, Last Seen=9. Pilot(0) and Faction(3) stay `Stretch` — untouched, not in this list.)

- [ ] **Step 2: Add the legend entry**

Read the existing legend `QLabel` rich-text string fresh (search for `"■</span> High Bounty"` to find it). Confirm it currently ends with:

```python
            '<span style="color:#5A2A2A;">■</span> At war (info only, not confirmed)'
        )
```

Add three more entries before the closing `)`:

```python
            '<span style="color:#5A2A2A;">■</span> At war (info only, not confirmed) &nbsp;'
            '<span style="color:#78C878;">■</span> Safe to engage &nbsp;'
            '<span style="color:#DCB450;">■</span> Caution (anarchy) &nbsp;'
            '<span style="color:#DCB4B4;">■</span> Unknown risk (likely bounty)'
        )
```

(Colors match the `QColor` values used in Step 4 below, expressed as hex: `QColor(120, 200, 120)` = `#78C878`, `QColor(220, 180, 80)` = `#DCB450`, `QColor(220, 180, 180)` = `#DCB4B4` — the last one intentionally reuses the exact same muted color already used for the existing "at war (info)" row highlight, keeping "uncertain/informational" visually consistent across this file.)

- [ ] **Step 3: Add the Engage Risk cell to `refresh()`'s row-building loop**

Read `refresh()` fresh. Confirm the current `items = [...]` list and the `is_high_bounty` computation just before it still match:

```python
                is_high_bounty = bool(
                    wanted_f
                    and isinstance(bounty, int)
                    and bounty >= 500_000
                    and str(rank).lower() in {"dangerous", "deadly", "elite"}
                )

                items = [
                    QTableWidgetItem(str(pilot)),
                    QTableWidgetItem(str(rank)),
                    QTableWidgetItem(str(ship)),
                    QTableWidgetItem(str(faction)),
                    QTableWidgetItem(str(power)),
                    QTableWidgetItem(enemy_txt),
                    QTableWidgetItem("Wanted" if wanted_f else ""),
                    QTableWidgetItem(bounty_txt),
                    QTableWidgetItem(last_seen),
                ]
                items[0].setData(Qt.ItemDataRole.UserRole, k)
```

Change to:

```python
                is_high_bounty = bool(
                    wanted_f
                    and isinstance(bounty, int)
                    and bounty >= 500_000
                    and str(rank).lower() in {"dangerous", "deadly", "elite"}
                )

                risk = rec.get("EngageRisk") or "unknown"
                risk_txt = {"safe": "Safe", "caution": "Caution", "unknown": "Unknown"}.get(risk, "Unknown")

                items = [
                    QTableWidgetItem(str(pilot)),
                    QTableWidgetItem(str(rank)),
                    QTableWidgetItem(str(ship)),
                    QTableWidgetItem(str(faction)),
                    QTableWidgetItem(str(power)),
                    QTableWidgetItem(enemy_txt),
                    QTableWidgetItem("Wanted" if wanted_f else ""),
                    QTableWidgetItem(bounty_txt),
                    QTableWidgetItem(risk_txt),
                    QTableWidgetItem(last_seen),
                ]
                items[0].setData(Qt.ItemDataRole.UserRole, k)
```

- [ ] **Step 4: Set the Engage Risk cell's own foreground color, after the row-wide color loop**

Read the current row-wide color-application loop and what follows it fresh. Confirm it currently reads:

```python
                for c, it in enumerate(items):
                    if bg:
                        it.setBackground(bg)
                    if fg:
                        it.setForeground(fg)
                    self.combat_table.setItem(r, c, it)

                if is_current:
                    selected_row = r
```

Add the Engage Risk color override directly after this loop (so it's applied after `setItem` has placed the item into the table, and after any row-wide `fg` the loop may have already set on it), before the `if is_current:` line:

```python
                for c, it in enumerate(items):
                    if bg:
                        it.setBackground(bg)
                    if fg:
                        it.setForeground(fg)
                    self.combat_table.setItem(r, c, it)

                risk_color = {
                    "safe": QColor(120, 200, 120),
                    "caution": QColor(220, 180, 80),
                    "unknown": QColor(220, 180, 180),
                }.get(risk, QColor(220, 180, 180))
                self.combat_table.item(r, 8).setForeground(risk_color)

                if is_current:
                    selected_row = r
```

(Applying to `self.combat_table.item(r, 8)` rather than `items[8]` guarantees this is the last write to that cell's foreground, overriding any row-wide `fg` the earlier loop already applied — e.g. a Hostile row's pink foreground would otherwise mask the risk color.)

- [ ] **Step 5: Update the `ShipTargeted` voice branch in `main_window.py`**

Read `edc/ui/main_window.py`'s `_tts_router` fresh, specifically the `ShipTargeted` branch and the module's import block. Confirm the current import line still reads:

```python
from edc.core.event_engine import EventEngine
```

Change to:

```python
from edc.core.event_engine import EventEngine, _engage_risk
```

Confirm the current `ShipTargeted` branch still matches:

```python
            if event_type == "ShipTargeted":
                if not evt.get("TargetLocked"):
                    return ""
                if int(evt.get("ScanStage", 0) or 0) < 3:
                    return ""

                rank         = str(evt.get("PilotRank") or "").strip()
                legal_status = str(evt.get("LegalStatus") or "").strip()
                wanted       = legal_status.lower() == "wanted"
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

                if we_active and power and ship_active:
                    is_enemy = True
                    is_high_value = False
                elif wanted and bounty > 500_000 and top_rank:
                    is_enemy = False
                    is_high_value = True
                else:
                    return ""

                pilot = evt.get("PilotName_Localised") or evt.get("PilotName") or ""
                ship  = evt.get("Ship_Localised") or evt.get("Ship") or ""
                key   = f"{pilot}|{ship}"
                if key in self._tts_spoken_ships:
                    return ""
                self._tts_spoken_ships.add(key)

                now = time.monotonic()
                if now < self._tts_ship_cooldown_until:
                    return ""
                self._tts_ship_cooldown_until = now + 6.0
                return CombatPhrases.ship_targeted(
                    ship, rank, power, is_enemy, wanted, bounty, is_high_value
                )
```

Replace with (preserves the "internal security"/`is_friendly` early silences exactly; only the trailing `if/elif/else: return ""` short-circuit is replaced so every remaining contact reaches the phrase-composition call, still gated by the existing dedup/cooldown):

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
                )

                pilot = evt.get("PilotName_Localised") or evt.get("PilotName") or ""
                ship  = evt.get("Ship_Localised") or evt.get("Ship") or ""
                key   = f"{pilot}|{ship}"
                if key in self._tts_spoken_ships:
                    return ""
                self._tts_spoken_ships.add(key)

                now = time.monotonic()
                if now < self._tts_ship_cooldown_until:
                    return ""
                self._tts_ship_cooldown_until = now + 6.0
                return CombatPhrases.ship_targeted(
                    ship, rank, power, is_enemy, wanted, bounty, is_high_value, engage_risk
                )
```

- [ ] **Step 6: Static syntax check**

Run: `python -c "import ast; ast.parse(open('edc/ui/panels/combat_panel.py', encoding='utf-8').read()); ast.parse(open('edc/ui/main_window.py', encoding='utf-8').read()); print('PARSE OK')"`
Expected: `PARSE OK`

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (no regressions from the constructor/signature changes).

- [ ] **Step 8: Manual live verification**

Start the app. Open the Combat tab. Confirm:
1. The contacts table shows a new "Engage Risk" column (Pilot, Rank, Ship, Faction, Power, Enemy, Wanted, Bounty, Engage Risk, Last Seen), with the legend above it explaining the 3 new colors.
2. A previously-encountered Hostile or Wanted contact shows "Safe" in green.
3. A rival-power contact encountered in your own controlled PowerPlay territory shows "Safe" in green.
4. An ordinary Clean contact with no PowerPlay relevance (e.g. the Vargerson-style case) shows "Unknown" in the muted color — previously this row had no distinguishing color or verdict text at all.
5. Existing row-background highlighting (Hostile red, PP-Enemy purple, high-bounty gold, wanted brown, at-war-info dark red) still displays exactly as before — this change must not have altered it.
6. Target-lock a ship (ScanStage 3) and confirm the spoken assessment now ends with one of "Clear to engage.", "Caution -- anarchy space, not guaranteed near a port.", or "Engaging will likely draw a bounty." — including for a plain Clean contact that previously produced no voice line at all from this branch.

- [ ] **Step 9: Commit**

```bash
git add edc/ui/panels/combat_panel.py edc/ui/main_window.py
git commit -m "feat: surface engage-risk verdict on the Combat tab and in voice

New \"Engage Risk\" column (Safe/Caution/Unknown, own color independent
of the existing row-highlight priority chain) makes the verdict from
_engage_risk() visible for the first time -- previously Hostile/PP-Enemy
were only implied by row color and an ordinary Clean contact (the real
bounty-risk case) got no visual signal at all. The ShipTargeted voice
branch's previous 'else: return \"\"' silenced most contacts before they
ever reached the assessment phrase; loosened so the risk clause is
actually heard for Hostile/low-bounty-wanted/plain-Clean contacts,
while keeping the existing law-enforcement/own-power silence and the
dedup/cooldown spam guards exactly as they were."
```
