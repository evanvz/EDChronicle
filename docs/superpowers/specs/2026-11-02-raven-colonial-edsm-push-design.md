# Raven Colonial and EDSM push (opt-in) — design

Date: 2026-11-02. Status: draft, awaiting Evan's review.

## Why

Raven Colonial build pages fall behind. The site only updates when a player's tool pushes journal data to it. Signing in with Frontier only proves who you are; it pulls no game data. Construction depot progress has no EDDN schema (checked against EDCD/EDDN `schemas/` 2026-11-02), so EDDN can't carry it. The squad needs two things on the build page: the materials still required, and how much each commander delivered.

EDSM: Evan sent journal data to EDSM through the EDMC EDSM plugin when the squad played on Xbox. He wants that back.

This reverses the earlier "never push to a third-party platform" rule, for these two platforms only, as opt-in (Evan, 2026-11-02).

## Goals

1. Raven Colonial: when the commander docks at a construction depot, update the build's "still needed" amounts. When the commander delivers, record the delivery under their name.
2. EDSM: upload the commander's live journal events, as the EDMC EDSM plugin did.
3. Both are off by default. Each is switched on in Settings with the commander's own name and API key.

## Non-goals

- Creating Raven Colonial projects, linking commanders, assigning commodities, fleet carrier cargo, or marking builds complete. Only builds that already exist on Raven Colonial get updates.
- Uploading history. Only events from live play are sent, never the journal replay at startup.
- Any other platform (Inara and others still need a new decision).
- Pushing other squad members' data. Each member needs their own EDChronicle (or SrvSurvey / EDMC plugin) and key.

## Anti-goals

- A push that sends duplicates (replay, the 15-second repeat of `ColonisationConstructionDepot`, retries).
- An API key that shows up in logs, in the UI after saving, or in error messages.
- Network calls on the UI thread. The app already has a stall watchdog; a slow server must not freeze it.
- A push that blocks or slows EDDN sending or journal processing when a third-party server is down.

## Raven Colonial

Write API, taken from two working clients: SrvSurvey `SrvSurvey/net/RavenColonial.cs` + `game/ColonyData.cs` (njthomson, master, read 2026-11-02) and EDMC-Ravencolonial `api/client.py` + `handlers/journal.py` (EDToolbox, last commit 2025-10-31). Base URL is the one `edc/core/raven_colonial.py` already uses (`_BASE_URL`).

| Step | Call | Body |
|---|---|---|
| Find the build | `GET /api/system/{SystemAddress}/{MarketID}` (exists: `get_project_for_station`) | — ; 404 = no build on Raven Colonial, skip |
| Still needed | `POST /api/project/{buildId}` | `{"buildId", "commodities": {name: RequiredAmount - ProvidedAmount}, "maxNeed": sum(RequiredAmount), "colonisationConstructionDepot": <the raw journal event>}` |
| Delivery | `POST /api/project/{buildId}/contribute/{cmdr}` | `{name: Amount}` from `ColonisationContribution.Contributions[]` |
| Check key | `GET /api/cmdr/` with header `rcc-key: <key>` | returns the commander name the key belongs to |

- Commodity name: journal `Name` with the leading `$` and the `_name;` suffix removed, lower-case (`$steel_name;` → `steel`). Both clients do this.
- The raw `colonisationConstructionDepot` must keep the journal's `timestamp` and `event` fields; Raven Colonial rejects the body without them (Fenris159/SrvSurvey PR #139).
- Send "still needed" only when it differs from what the build already shows (SrvSurvey compares against the project's `commodities`). The existing `_colonisation_depot_last_seen` dedup already drops the unchanged 15-second repeats.
- **Unverified: whether writes need the key.** Neither SrvSurvey nor the EDMC plugin sends `rcc-key` on these two writes; SrvSurvey only sends it for fleet carrier and system-site writes. d47's design (dseelinger/d47 #1412, 2026-10-20) says every write carries the key. Builder's call: send the `rcc-key` header on both writes anyway, and confirm with one live delivery.
- `{cmdr}` in the contribute URL is the name `GET /api/cmdr/` returns for the key, so deliveries land under the right commander on the page.
- New journal event handled: `ColonisationContribution` (not handled anywhere in the app today). `ColonisationConstructionDepot` is already handled in `main_window.py` (`_save_colonisation_depot`).

## EDSM

Taken from EDMC's `plugins/edsm.py` (EDCD/EDMarketConnector, read 2026-11-02). EDSM's own API page (`edsm.net/en/api-journal-v1`) refused the fetch (403), so these details come from EDMC's working code, not EDSM's docs.

- `POST https://www.edsm.net/api-journal-v1`, form fields: `commanderName`, `apiKey`, `fromSoftware`, `fromSoftwareVersion`, `fromGameVersion`, `fromGameBuild`, `message` (JSON array of journal events).
- `GET https://www.edsm.net/api-journal-v1/discard`: the event names EDSM doesn't want. Fetch once per session; don't send those.
- Each event gets transient fields added: `_systemName`, `_systemCoordinates`, `_stationName`, `_shipId`.
- Batch events and send on location-type events (`FSDJump`, `Location`, `CarrierJump`, `Docked`) and at shutdown, like EDMC's `should_send`.
- Reply `msgnum`: 1xx = accepted; 2xx = refused, log and drop; 5xx = server trouble, keep the batch and retry later. On HTTP 429, wait until the rate-limit reset time.
- EDSM only accepts Live galaxy data (EDMC checks this). Our journals are Live.
- The EDSM commander name can differ from the in-game name; it's its own setting.

## Settings

A new "Sharing" group in the Settings dialog, next to the EDDN switch:

- Raven Colonial: on/off, API key (from `ravencolonial.com/user`), a Test button that runs `GET /api/cmdr/` and shows the commander name it returns.
- EDSM: on/off, EDSM commander name, API key (from `edsm.net/settings/api`), a Test button.
- A status line for each: last send time and result (for example "Delivered 120 steel to <build>" or "Build not on Raven Colonial").
- Keys are entered in password-style fields and never displayed again after saving.
- **Key storage (Evan, 2026-11-02): in our database, encrypted.** A new table in `persistence/schema.py`, `push_credentials (service TEXT PRIMARY KEY, name TEXT, secret BLOB)`, one row per service (`ravencolonial`, `edsm`). `secret` is the key encrypted with Windows DPAPI (`CryptProtectData` / `CryptUnprotectData` from `crypt32` through `ctypes`, current-user scope, no new dependency). Windows holds the encryption key, so the app stores none. A copied database is unreadable bytes for another Windows user or machine: on the second laptop the keys are entered once. A secret that fails to decrypt counts as "not set" and the status line says to re-enter it.
- The on/off switches and the EDSM commander name stay in `settings.json` with the other settings; only keys go in the database.
- Only events from the commander the keys belong to are sent. Builder's call on how: compare the journal `Commander` with the configured name.

## Decided (Evan, 2026-11-02)

1. Keys: in the database, encrypted (see Settings).
2. EDSM scope: what EDMC's EDSM plugin sends — every live event not on EDSM's discard list, with EDMC's `should_send` batching rules and its synthesised `Materials` event on `LoadGame`.

## Left to the builder

- Where the sending code lives (one module per platform, next to `raven_colonial.py`), the worker thread shape (QThread kept for the app's lifetime per CLAUDE.md), retry timing, and the status line wording.
- Tests: commodity name conversion, payload shapes, replay guard, dedup, 404 skip, key never in logs.
- Live confirmation before calling it done: one depot dock and one delivery showing on the Raven Colonial page; one jump showing on EDSM.
