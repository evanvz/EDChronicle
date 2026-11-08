# Colonisation: Design My System — design

Date: 2026-11-08. Status: approved by Evan 2026-11-08 ("look good"), with depot-driven status added.
Repo: EDChronicle only. Builds on the 2026-11-04 system planner (`docs/superpowers/specs/2026-11-04-colonisation-system-planner-design.md`).

## Why

Evan's squad claimed its first system on 2026-11-07: HIP 109508. The primary is a Coriolis, "Equiano Territory", above body A 8 b, built solo. Evan has entered and confirmed the slot counts for every body.

The existing Design window can plan this system, but it falls short in four ways:

- It only opens from the candidate finder. That finder lists systems you could still claim, not the one you're building.
- The plan is shown as a list with no step numbers. Nothing says it's a build order.
- The plan starts from an empty system every time. It has no idea what is built, under construction, or chosen by hand.
- The "Full build" plan placed four Dodec starports on the A 8 bodies. That is about 236,000 t of hauling each, for a solo builder. Each one put three economies into one market, and the same window then warned about it. Evan: "if the four dodecs and four economy warnings is highlighted, then why are we using it."

Evan wants one window where he sees every body and slot, follows a numbered build order, can change any planned build, and tracks each build from planned to complete.

## Goals

1. **Design My System button** on the colonisation panel. It opens the Design window for the system the commander is in now, without going through the finder.
2. **Numbered build order.** Step 1 is the primary port. Then come the remaining builds, in the order the plan places them.
3. **Per-slot choice.** The auto-plan fills the system as it does today, using the system type picker, Solo/Group and the primary body. Evan can change the facility on any step at any time, and the rest of the plan re-fits around his choices.
4. **Status per build:** Planned, Building or Complete. It's set automatically from construction depots where possible (see "Status from depots"), and Evan can always set it by hand.
5. **No poor builds.**
   - If the only thing that fits a slot would put a third economy into a market, the planner leaves the slot empty.
   - The empty slot is shown as a row reading "left empty: <reason>", so Evan can decide later.
6. **Solo means no Tier 3 ports.** With Solo selected, the planner places no Dodec starport and no large planetary port. The primary port rule stays as it is: solo means Coriolis.
7. **Saved on this PC.** The plan, Evan's choices and the statuses are stored in the app's own `edhelper.db`.

## Non-goals

- Sharing plans with the squad, or pushing them through EDDataHub or Raven Colonial. Evan: save it on our PC. Slot counts stay shared through the hub, as now.
- Optimal solving with integer programming. The 2026-11-04 non-goal stands.
- Choosing what goes into a slot left empty. That's Evan's call afterwards.
- Haul or commodity planning per step. The existing tonnage per step stays as information only.

## Anti-goals

- A plan that recommends a build it warns against. If something is flagged as poor, it isn't placed.
- Losing Evan's choices or statuses when the plan is re-run, the window is closed, or the app restarts.
- The planner overriding anything Evan has chosen by hand, or anything marked Building or Complete.

## Decisions (Evan, 2026-11-08)

- Order of work: the button, then the numbered order, then per-slot choice with status.
- A poor slot stays empty, with a warning. It is never filled with the poor option.
- Solo builder, so no Dodecs.
- Stored locally, not shared.

## How it behaves

### Opening

- A "Design My System" button sits on the colonisation panel, next to the existing finder button.
- It uses the current system's SystemAddress (id64) and name from game state, and opens the same `ColonisationDesignDialog` the finder uses.
- It is disabled when there's no EDDataHub URL, because the window loads the system's bodies from the hub. Same tooltip as the finder button.
- It is also disabled when no current system is known yet.

### The plan table

- A new first column, **#**, numbers the rows 1, 2, 3, … in plan order.
- Plan order is placement order. The construction-point balance is computed in that order, so every step can be paid for by the steps before it.
- A **Status** column holds a selector: Planned, Building, Complete.
- The **Step** cell becomes a selector listing every facility that could go in that slot. A slot is one body plus orbital or surface.
- Rows left empty by the poor-build rule:
  - show "left empty", with the reason in the Unlocks/Needs area;
  - are greyed;
  - still show the selector, so Evan can fill the slot by hand.

### Fixed steps and re-planning

- A step is **fixed** when Evan has picked its facility by hand, or set its status to Building or Complete.
- A re-plan happens on any change to the type, Solo/Group, the primary body, a facility choice or a status. It runs in this order:
  1. Place the primary, then every fixed step, using their slots, construction points and requirements.
  2. Run the existing type passes on what's left, with the two new rules: no Tier 3 ports when Solo, and leave a slot empty rather than add a third economy.
- If a fixed step can't be paid for or can't be placed, it stays in the list anyway. Possible causes are a requirement that isn't built yet, or a slot that no longer exists. The step is marked red with the reason. The planner never drops it.
- Setting a step back to Planned and to the facility the auto-plan would choose un-fixes it.

### The poor-build check

- The existing check runs after planning: a market holding more than two economies, ignoring Colony and Terraforming, with the "strong link: same body" rule in `colonisation_design._clash`.
- It moves to before each placement.
- Placing a facility that would push its market past two economies fails. The planner then tries the next option in that pass.
- If a pass ends with a slot it wanted to fill but couldn't, that slot becomes a "left empty: <market> would get a third economy (<economies>)" row.
- The after-planning warning stays, as a safety net for fixed steps that cause a clash.

### Saving

- New table in `edhelper.db`, created through the existing migration list. One row per step the user has touched:
  - `system_address`
  - `body_name`
  - `location` (orbital / surface)
  - `slot_index` (which slot of that kind on that body)
  - `facility` (the key from `settings/colonisation_facilities.json`)
  - `status`
  - `market_id` (the linked depot, nullable)
  - `updated_at`
- Per system, also store the last picks: system type, Solo/Group and primary body. That way the window reopens the way Evan left it.
- Writes happen on change. Rows that are only auto-planned aren't stored; they're recomputed.

## Settled after the builder check

- **Slot counts are totals.** Evan entered them from the Architect View before the claim and the first build, so occupied slots are included. The primary, and every Building or Complete step, takes a slot out of those totals. (Settled by Evan's description.)
- **Typed path only.** The numbering, selectors, statuses and saving apply to the typed plan (`plan_by_type`): a type is chosen and all slots are confirmed. The old template view stays read-only. It gets the # column, but no selectors or status. (My call.)
- **Fixed-step order.** The pre-pass places the primary, then Complete steps, then Building steps, then hand-picked Planned steps. Within each group, steps are placed so their requirements are met. Steps are numbered in that order, and the auto passes continue the numbering. A fixed step whose requirement isn't placed yet goes red but keeps its number. (My call.)
- **Market for the economy check.**
  - It's the existing rule, `_clash` with the same-body strong link, counted per body.
  - Before a placement, the planner counts the economies already on the facility's body plus the new facility's economy.
  - A hub gets its economy from `_HUB_ECON`. A facility with no economy and no `_HUB_ECON` entry adds none.

  (My call: the same rule the after-plan warning already uses.)
- **Slot identity.**
  - `slot_index` runs 0..n-1 per (body, location), in the order steps take that kind of slot.
  - A saved row whose index is at or above the body's current count goes red as "slot no longer exists". It isn't deleted.
  - Bodies are matched by name, as the slot table already does.

  (My call.)
- **Every touched step is stored.** A Building or Complete status on an auto-planned step stores it with its facility, and it becomes fixed. Un-fixing is an explicit "Reset to auto" on the row. It deletes the stored row. (My call.)
- **Solo blocks every Tier 3 port except the primary.** Dodec starport and large planetary port are blocked in every pass, including Pass 3's early surface port and Pass 4's surface fallback. `port_cost` counting is unchanged. (My call.)
- **Status from depots** (Evan, 2026-11-08: "if a slot is in building would be the depot event"):
  - **The primary is automatic.** A `colonisation_depots` row in this system whose raw docked name was the colonisation ship is the primary. This version ships with the `$EXT_PANEL_ColonisationShip` token stripped before saving, so the row has to be recognised differently. Options: a stored flag, or the depot that is the system's first and only one while the primary isn't Complete. That choice is the builder's. The primary step shows Building while that depot is open, and Complete once it reports `complete`.
  - **Other sites are linked by hand.** ColonisationConstructionDepot carries only MarketID: no body, no facility type. So each of this system's depots that isn't linked yet is listed in the window with a "link to step" selector. A linked step is stored with the depot's `market_id`. It shows Building until the depot reports complete, then Complete. A manual status still overrides.
- **Left-empty rows** come after the numbered steps. They have no number and count zero toward haul, points and outcome stats. (My call.)

## Constraints

- PyQt6 and SQLite, as the app uses now. Database access follows the existing thread rules: a new Database per thread, and QThreads kept referenced.
- Planner code stays pure, with no Qt, in `edc/core/colonisation_planner.py`, so it can be tested like the existing planner tests.
- Facility data comes only from `settings/colonisation_facilities.json`.
- Window style matches the existing Design window.

## Left to the builder

- Where exactly the button sits and what it looks like, within the colonisation panel's existing button row.
- How the slot index is assigned when a body has several slots of one kind. It must stay stable across re-plans for fixed steps.
- Which facilities the selector lists. The minimum is everything whose location matches the slot. Whether to hide or grey out facilities whose requirements aren't met is the builder's call.
