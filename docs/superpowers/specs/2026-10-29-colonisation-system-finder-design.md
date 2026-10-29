# Colonisation System Finder — Design

Date: 2026-10-29. Projects: EDDataHub (data + search) and EDChronicle (UI).

## Intent

Evan wants to find a system worth colonising anywhere in the inhabited bubble, not only within the 15 ly sphere around one system that the Colonisation tab checks today. He may claim one himself; it is not a squadron project, but the squad's location matters.

"Worth colonising" means two things, in Evan's words: **the number of different port types you could build there, and the economy those ports would give.**

This replaces the parked "EDDataHub system dump" task (memory `project-eddatahub-system-dump`). That task was a third fallback for the candidate lookup; this design is the bigger version of it.

## Goals

- **Search the whole bubble** for unclaimed, unpopulated systems that can be colonised.
- **Rank them** by the port types the system's bodies allow and the economies those ports would give.
- **Show the squad's location.** Each result shows its distance to the nearest system where Evan's squadron faction is present. Results can be filtered and sorted by it.
- **Use our own data.** The data and the search live on EDDataHub. It reads Spansh's dump once and refreshes it weekly, so a search doesn't depend on Spansh or EDSM being up.

## Non-goals

- **No build planning.** It doesn't plan what to build, commodity lists or construction order. Raven Colonial and the existing Colonisation tab do that.
- **No claiming or "being colonised" check from our own data.** The hub can't know that a system has just been claimed. The app keeps using Spansh's live flag for that, where Spansh is reachable.
- **No change to the existing 15 ly candidate lookup** or its EDSM → Spansh fallback.
- **Nothing for public installs.** With no hub configured, the new search isn't offered.

## Anti-goals: it fails if…

- **A search is slow.** The market search on the hub took 8–40 s from the spinning disk, and Evan rejected it (memory `project-eddatahub-integration`). A colonisation search must answer in about 1 s.
- **The ranking claims more than the data supports.** A port type is only offered when the body data actually shows what it needs. Unknown bodies count as unknown, not as "no".
- **It pushes our data anywhere.** Third-party sites are only read (memory `feedback-no-third-party-data-push`).

## Constraints

- **Server:** spinning disk, 11 GB RAM (6.5 GB free), 434 GB disk free (measured 2026-10-28).
- **Dump sizes (HTTP HEAD, 2026-10-29):**
  - Spansh `galaxy.json.gz`: 118 GB, every system with bodies and stations.
  - Spansh `galaxy_7days.json.gz`: 3.2 GB.
  - Spansh `galaxy_1month.json.gz`: 5.6 GB.
  - EDSM `systemsWithCoordinates.json.gz`: 3.7 GB, no bodies.
- **The hub already has `region_systems`** (`eddatahub/region.py`, migration 014). It holds every system within 30 ly of a populated system, from EDSM's coordinate dump, refreshed weekly and fully monthly. It stores id64, name and position only. This is the candidate universe; colonisation range (~15 ly) sits inside it.
- **Hub conventions:**
  - Python and Postgres.
  - Numbered SQL migrations in `sql/`.
  - A systemd timer per job in `deploy/`.
  - JSON endpoints in `eddatahub/web.py`.
  - Tests run against the local test Postgres (`C:\Dev\pgdev`, port 55432).
  - Deploy is `sudo bash /opt/eddatahub/app/deploy/update.sh`.
- **App conventions:**
  - PyQt6.
  - Worker QThreads with their own DB connection; a QThread must outlive its work.
  - `style.TAB_STYLE` for tabs.
  - The hub base URL is in config `eddatahub_url`.
  - Hub calls go through `edc/core/eddatahub_client.py` with a timeout and a back-off.

## Decided

### Data: on EDDataHub, from Spansh's dump, limited to the bubble

1. **Read the dump without storing it.** The hub streams Spansh `galaxy.json.gz` straight from the download, the way `region.py` streams EDSM. It keeps only systems that are in `region_systems` and have population 0 (or none).
2. **Store a summary of each body**, not the whole body record. It holds the fields the ranking needs:
   - body type and subtype;
   - landable;
   - rings, and belts on a star;
   - gas giant;
   - atmosphere;
   - volcanism;
   - signals, if present;
   - distance to arrival.
   Each system also keeps its main star type and the dump's update time.
3. **Refresh.**
   - Weekly from `galaxy_7days.json.gz`: upsert the systems it contains, then recompute their scores.
   - **The first import must be a full read** of `galaxy.json.gz`, because the weekly file only covers recently updated systems.
   - After that, a full re-read **monthly**, so systems that become claimable as new colonies appear are picked up.
   - **Only claimable systems are stored** (within 15 ly of a populated system). This was Evan's choice, option B, on 2026-10-29: the region holds 1,566,939 systems, about 390 MB, which was over the memory gate; the claimable subset is about 130 MB (an estimate). Bodies average 5.8 per unpopulated system, and 36.7% of systems have none recorded (7-day sample).
   - Systems that become populated drop out of results; the weekly file shows their population.
4. **Precompute.** At import time each system gets:
   - the set of port types its bodies allow;
   - the economies those ports would give;
   - a score.
   A search then reads one small table with indexed columns; no body rows are read during a search.
5. **Measure first.** Count the candidate systems and body rows from a sample before building the import. Check the table fits in the server's spare RAM. If it doesn't, stop and come back to Evan.

### Search: a hub endpoint

`GET /api/colonisation-search` takes these parameters:
- `x, y, z`: the centre;
- `radius`: up to a cap, the builder's call;
- `port_type`: optional, repeatable;
- `economy`: optional, repeatable;
- `near`: optional list of squad system id64s, with `near_max`, an optional limit in ly. The hub looks up their positions in `region_systems`, because the app's Player Faction overview has id64s but not always coordinates (*my call, from the builder check*);
- `limit`: default 100.

It returns the systems sorted by score, then distance. Each row carries:
- name and id64;
- coordinates and distance;
- port types, economies and score;
- body count;
- distance to the nearest `near` point;
- data age.

`GET /api/colonisation-system?id64=` returns one system's bodies, with the port types each body allows.

### App: a "Find Systems…" window off the Colonisation tab

The Colonisation tab has no sub-tabs today. A **"Find Systems…" button** opens a non-modal window, like the app's other detail dialogs. *Evan's call was "you decide"; the window rather than a new tab is my call, because the tab is one panel today.*

**Search row:**
- Centre system: defaults to the current system; any system name can be typed.
- Radius.
- Port type filter.
- Economy filter.
- A "near squad" checkbox with a ly limit.
- Search.

**Results table** (sortable, filter-by-name box, the System Status table pattern):

| System | Dist (ly) | To squad (ly) | Score | Port types | Economies | Bodies | Data age |
|---|---|---|---|---|---|---|---|

- **Port types** are shown as short words (Orbital, Asteroid, Surface, Outpost, and whatever the rules source defines).
- **Selecting a row** fills a lower pane with that system's bodies and the port types each allows.
- **Clicking a system name** copies it.
- **When the user picks a row,** the app asks Spansh for its live "being colonised" flag (`_spansh_claimed` already exists) and shows "claimed" or "free". This doesn't happen for every row.

**Squad points.** The app already knows the squadron faction's systems: Player Faction overview, `get_player_faction_overview`. It sends their id64s as `near`.

**Systems with no bodies in the dump** (never scanned) are still listed, showing "unknown" port types and the lowest score. They aren't hidden, because an unscanned system may still be good (*my call*).

**No hub.** The button is hidden or disabled with a tooltip saying it needs EDDataHub.

## Left to the builder

- **The rules source.** Which body allows which port type, and which economy each gives. Candidates:
  - Evan's bookmarked `ed-colonisation-planner` (logic only, memory `reference-ed-colonisation-planner`);
  - the SrvSurvey / Raven Colonial wiki;
  - Frontier's Trailblazers notes.

  Pick one, cite it with the date checked in the code, and keep the rules in one data file so they can be corrected.
- **The score formula.** It must reward variety of port types first and economy variety second. Keep it simple and show it in a tooltip.
- **Table layout and indexes** on the hub.
- **The radius cap.**
- **Exact field names** from Spansh's dump. Read a sample, and check against Spansh's own docs or the data itself.
- **The weekly timer slot,** clear of the other hub timers (02:00, 03:00, 04:00 UTC daily; Sunday 12:00 UTC).

## Later, not in this design

- **PowerPlay Cascade/Vulnerable** on the hub (memory `project-eddatahub-system-dump`). A separate design.
- **Per-system hub data on visit** (item 8, 2026-10-29). The hub would keep body signals, RES sites and codex species per system, and the app would ask on each jump. A separate design.
