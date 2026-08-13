# Show Active War Opponent on the Player Faction Card — Design

## Context

The Player Faction card's Forecast column already predicts *upcoming* conflicts via `conflict_risk` (`persistence/repository.py::get_faction_predictions()`): when a rival faction's influence converges within 5 points of the tracked faction's (both above a 7% floor), it shows `⚔ Conflict risk vs {name} (Δ{diff}%)`.

Live use surfaced the gap: once a system is *already* at War/CivilWar, the card's action text (`_bgs_action_core()` in `edc/ui/panels/player_faction_panel.py`) only shows a generic `⚔ War/Civil War active — combat kills for this faction help win it.` — no opponent name, no opponent influence. The `conflict_risk` predictor can't fill this in either: it's proximity-based (small influence delta), and a real active war can exist with a large gap (the case that surfaced this: 60% vs the next-closest faction at 20%, nowhere near the 5-point convergence threshold).

## Design

### Identifying the opponent

Elite Dangerous doesn't record "faction A is at war against faction B" anywhere — `War`/`CivilWar` is a per-faction state. A war between two factions in the same system is inferred by both factions independently showing that state. So: when the tracked faction's own latest snapshot shows War/CivilWar (via `faction_state` or `active_states`, same fields `_bgs_action_core()` already checks), look up the other factions present in that system's most recent snapshots and find any whose *own* `faction_state`/`active_states` also shows War/CivilWar. Proximity/influence is irrelevant to this check — a system can have a war between a 60% faction and a 20% faction just as validly as two 40% factions.

If EDSM's data is asymmetric (only the tracked faction shows War, no other faction in the system currently shows it too — a known real EDSM data-lag possibility), the result is "at war, opponent unknown" — shown honestly, not guessed via influence proximity.

### `Repository.get_faction_predictions()` — extended

New `active_war` key per entry, alongside the existing `conflict_risk`:
- `None` — the tracked faction is not currently at War/CivilWar in this system.
- `{"faction_name": None, "influence": None}` — tracked faction IS at war, no symmetric opponent found (unknown).
- `{"faction_name": "X", "influence": 0.2}` — tracked faction IS at war; faction X's latest snapshot also shows War/CivilWar, at 20% influence.

Determined by two additions to the existing per-system loop: (1) one small query fetching the tracked faction's own latest `faction_state`/`active_states` for that system (mirrors the existing `MAX(snapshot_date)` pattern already used for the `conflict_risk` rivals query); (2) if that shows war, a second query fetching every other faction's latest snapshot at that `system_address` (unfiltered by influence, unlike the `conflict_risk` rivals query), each checked in Python for its own war state via a small local helper — `persistence/repository.py` doesn't import UI code, so this reuses the *logic* of `_bgs_action_core()`'s war check (`"war" in active_states or "civilwar" in active_states or faction_state in {"war", "civilwar"}`), not the function itself; a minimal local equivalent, not a cross-layer import.

### `_format_forecast()` — new top priority

`active_war` becomes the highest-priority branch, checked before `conflict_risk` (an active war is more informative than a risk prediction — the risk already materialized):

```
⚔ At War vs {faction_name} ({influence:.1f}%)          — opponent known
⚔ At War — opponent unknown (EDSM data incomplete)      — opponent not found
```

Both use the same red (`#FF6B6B`) already used elsewhere for active War in `_bgs_action_core()`. `conflict_risk`, expansion/retreat, and trend fall through unchanged below this new check when `active_war` is `None`.

### Testing

Fully synthetic-testable against a real temp SQLite DB (this repo's established convention, e.g. `tests/test_faction_snapshot_freshness.py`, `tests/test_odyssey_farming_candidates.py`): seed `faction_snapshots` rows for a tracked faction at War plus a rival also at War, assert `active_war` names the rival with the right influence; seed a tracked faction at War with no other faction showing War, assert `active_war` is the "opponent unknown" shape; seed a tracked faction NOT at war, assert `active_war` is `None`. `_format_forecast()`'s new branch is a pure function of its input dict, tested the same way its existing branches presumably already are (or directly, if none exist yet — check before writing).

No new files — extends the two existing functions.
