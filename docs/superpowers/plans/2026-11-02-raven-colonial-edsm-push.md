# Raven Colonial and EDSM Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in pushes of live journal data to Raven Colonial (depot "still needed" + per-commander deliveries) and EDSM (journal upload, EDMC rules), with API keys stored encrypted in our DB.

**Architecture:** One module per platform in `edc/core/`, each a queue + daemon-thread sender shaped like `edc/core/eddn_publisher.py` (`start()` / `stop()` / non-blocking enqueue). Keys live in a new `push_credentials` table, encrypted with Windows DPAPI via `ctypes`. `main_window.py` loads keys once on the UI thread, hands plaintext to the senders in memory, and feeds them live events next to the existing EDDN call.

**Tech Stack:** Python 3.12, PySide6, `requests`, `ctypes` (crypt32), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-raven-colonial-edsm-push-design.md`

## Global Constraints

- Off by default. Nothing is sent unless the platform's switch is on and its key is set.
- Live play only: never send while `self._replaying` is True.
- Only events from the commander the keys belong to: journal `Commander` (from `self.state.commander`) must equal the key's commander name (Raven: name from `GET /api/cmdr/`; EDSM: `edsm_commander_name` setting is EDSM's name, so compare against the in-game name saved alongside the key — see Task 1 `name` column).
- No network call on the UI thread. Sender threads never touch SQLite (CLAUDE.md: no shared connections across threads).
- An API key never appears in a log line, an exception message, a status line, or a widget after saving.
- No new dependencies.
- Raven base URL: reuse `_BASE_URL` from `edc/core/raven_colonial.py`.
- EDSM endpoints: `https://www.edsm.net/api-journal-v1` (POST, form fields) and `https://www.edsm.net/api-journal-v1/discard` (GET).

## Review Focus

1. Startup journal replay while a switch is on → zero requests sent (Task 4 test `test_no_push_during_replay`).
2. `ColonisationConstructionDepot` repeating every 15 s unchanged → one POST, not one per tick (Task 2 `test_needs_sent_only_when_changed`).
3. Raven Colonial down / timing out → app keeps processing events, queue drops on overflow, nothing raised to the UI thread (Task 2 `test_post_failure_is_logged_not_raised`).
4. Key copied DB on the other laptop → decrypt fails → treated as "not set", status asks to re-enter (Task 1 `test_unprotect_garbage_returns_none`).
5. A different commander logged in (alt account) → nothing sent (Task 4 `test_no_push_for_other_commander`).

---

### Task 1: Encrypted key store

**Files:**
- Modify: `persistence/schema.py` (`SCHEMA_SQL`, after `dismissed_faction_systems`)
- Create: `edc/core/push_credentials.py`
- Test: `tests/test_push_credentials.py`

**Interfaces:**
- Produces:
  - `protect(data: bytes) -> bytes`, `unprotect(blob: bytes) -> Optional[bytes]` (DPAPI `CryptProtectData`/`CryptUnprotectData`, current user, no entropy; `None` on any failure)
  - `save_key(db: Database, service: str, name: str, key: str) -> None`
  - `load_key(db: Database, service: str) -> Optional[tuple[str, str]]` → `(name, key)`; `None` when missing or undecryptable
  - `clear_key(db: Database, service: str) -> None`
  - Service ids: `RAVEN = "ravencolonial"`, `EDSM = "edsm"`

- [ ] **Step 1: Add table to `SCHEMA_SQL`**

```sql
CREATE TABLE IF NOT EXISTS push_credentials (
    service TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    secret  BLOB NOT NULL
);
```

`name`: Raven = in-game commander name returned by the key check; EDSM = in-game commander name the EDSM key was saved for. The EDSM account name is a setting (Task 4).

- [ ] **Step 2: Write failing tests**

```python
def test_protect_round_trip():
    assert unprotect(protect(b"abc123")) == b"abc123"

def test_protected_bytes_hide_plaintext():
    assert b"abc123" not in protect(b"abc123")

def test_unprotect_garbage_returns_none():
    assert unprotect(b"not a dpapi blob") is None

def test_save_load_clear(tmp_path):
    db = Database(tmp_path / "t.db")
    save_key(db, RAVEN, "B0B R0GERS", "k-1")
    assert load_key(db, RAVEN) == ("B0B R0GERS", "k-1")
    raw = db.execute("SELECT secret FROM push_credentials").fetchone()[0]
    assert b"k-1" not in bytes(raw)
    clear_key(db, RAVEN)
    assert load_key(db, RAVEN) is None

def test_load_undecryptable_is_none(tmp_path):
    db = Database(tmp_path / "t.db")
    db.execute("INSERT INTO push_credentials VALUES ('edsm', 'X', x'00ff')")
    assert load_key(db, EDSM) is None
```

Match `Database`'s actual commit/fetch API in `persistence/database.py` when writing these.

- [ ] **Step 3: Run** `.venv\Scripts\python -m pytest tests/test_push_credentials.py -q` → FAIL (module missing)
- [ ] **Step 4: Implement `edc/core/push_credentials.py`** — `DATA_BLOB` ctypes struct, `LocalFree` the output buffer. Mark the module Windows-only in its docstring (the app is Windows-only).
- [ ] **Step 5: Run tests** → PASS; then full suite `.venv\Scripts\python -m pytest -q` → no new failures
- [ ] **Step 6: Commit** `feat: encrypted push credential store (DPAPI)`

---

### Task 2: Raven Colonial sender

**Files:**
- Create: `edc/core/raven_colonial_push.py`
- Test: `tests/test_raven_colonial_push.py`

**Interfaces:**
- Consumes: `get_project_for_station(system_address, market_id)` and `_BASE_URL` from `edc/core/raven_colonial.py`
- Produces:
  - `commodity_key(journal_name: str) -> str` — strip leading `$`, trailing `_name;`, lower-case
  - `needs(evt: dict) -> dict[str, int]` — `{commodity_key(Name): RequiredAmount - ProvidedAmount}` for entries with `RequiredAmount > 0`
  - `needs_payload(evt: dict, build_id: str) -> dict` — `{"buildId", "commodities": needs(evt), "maxNeed": sum(RequiredAmount), "colonisationConstructionDepot": evt}` (raw event unchanged, so `timestamp` and `event` stay)
  - `contribution_payload(evt: dict) -> dict[str, int]` — from `Contributions[]`, `Amount > 0` only
  - `check_key(key: str) -> Optional[str]` — `GET {_BASE_URL}/api/cmdr/` with header `rcc-key`; commander name or `None`. Synchronous; called from a worker (Task 4).
  - `class RavenColonialPusher(key: str, cmdr: str, on_status: Callable[[str], None])` with `start()`, `stop()`, `submit(evt: dict, system_address: int) -> None` (non-blocking; accepts `ColonisationConstructionDepot` and `ColonisationContribution`, ignores other events)
- Behaviour inside the worker thread:
  - build lookup cached per `(system_address, MarketID)`; 404 → cache `None`, `on_status("Build not on Raven Colonial")`, skip
  - depot: POST `/api/project/{buildId}` only when `needs(evt)` differs from the last sent value for that build (initialise from the project's `commodities`)
  - contribution: POST `/api/project/{buildId}/contribute/{quote(cmdr)}` with `contribution_payload`
  - every write sends headers `User-Agent` (from `edc.version.USER_AGENT`) and `rcc-key`
  - failures: log at warning with status code only, `on_status("Raven Colonial: send failed")`, never raise; queue `maxsize` like `eddn_publisher._QUEUE_MAX`, drop on full with a warning

- [ ] **Step 1: Write failing tests** (monkeypatch `requests.get` / `requests.post`, or the module's session; use the real events below)

```python
DEPOT = {"timestamp": "2026-11-01T18:06:00Z", "event": "ColonisationConstructionDepot", "MarketID": 4224896003,
         "ResourcesRequired": [{"Name": "$aluminium_name;", "RequiredAmount": 40536, "ProvidedAmount": 40000},
                               {"Name": "$steel_name;", "RequiredAmount": 100, "ProvidedAmount": 100}]}
CONTRIB = {"timestamp": "2026-11-01T18:01:37Z", "event": "ColonisationContribution", "MarketID": 4224896003,
           "Contributions": [{"Name": "$Aluminium_name;", "Amount": 71}, {"Name": "$Steel_name;", "Amount": 1147}]}

def test_commodity_key_mixed_case():
    assert commodity_key("$Aluminium_name;") == "aluminium"

def test_needs_payload_shape():
    p = needs_payload(DEPOT, "b-1")
    assert p["commodities"] == {"aluminium": 536, "steel": 0}
    assert p["maxNeed"] == 40636 and p["buildId"] == "b-1"
    assert p["colonisationConstructionDepot"]["timestamp"] == DEPOT["timestamp"]
    assert p["colonisationConstructionDepot"]["event"] == "ColonisationConstructionDepot"

def test_contribution_payload():
    assert contribution_payload(CONTRIB) == {"aluminium": 71, "steel": 1147}

def test_needs_sent_only_when_changed(): ...      # submit DEPOT 3x → exactly 1 POST to /api/project/b-1
def test_contribution_posts_under_cmdr(): ...    # URL ends /contribute/B0B%20R0GERS, json == {"aluminium": 71, "steel": 1147}
def test_unknown_build_skips_and_reports(): ...  # lookup 404 → 0 POSTs, on_status got "Build not on Raven Colonial"
def test_post_failure_is_logged_not_raised(): ...# post raises → submit returns, on_status got "Raven Colonial: send failed"
def test_key_never_logged(caplog): ...           # failing POST with key "secret-k" → "secret-k" not in caplog.text
def test_writes_send_rcc_key_header(): ...
```

Fill each `...` with the arrangement and the single assertion in its comment. Drive the worker deterministically (e.g. call the per-item handler directly, or `stop()` to drain).

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_raven_colonial_push.py -q` → FAIL
- [ ] **Step 3: Implement** `edc/core/raven_colonial_push.py`
- [ ] **Step 4: Run tests** → PASS; full suite → no new failures
- [ ] **Step 5: Commit** `feat: Raven Colonial depot and delivery sender`

---

### Task 3: EDSM sender

**Files:**
- Create: `edc/core/edsm_push.py`
- Test: `tests/test_edsm_push.py`

**Interfaces:**
- Produces:
  - `LOCATION_EVENTS = ("CarrierJump", "FSDJump", "Location", "Docked")`
  - `should_send(pending: list[dict], event: str, newgame_docked: bool) -> bool` — port of EDMC `plugins/edsm.py::should_send` (send on `Shutdown`/`Fileheader`; `Docked` always; `Cargo` unless `newgame_docked`; anything except `CommunityGoal`, `ModuleBuy`, `ModuleSell`, `ModuleSwap`, `ShipyardBuy`, `ShipyardNew`, `ShipyardSwap`). Skip EDMC's `NavBeaconScan` special case — the app has no equivalent counter; note it in a comment.
  - `with_transient(evt: dict, system: str, coords: tuple, station: Optional[str], ship_id: Optional[int]) -> dict` — copy with `_systemName`, `_systemCoordinates`, `_stationName`, `_shipId`
  - `materials_from_loadgame(...)` is NOT needed: the app reads the real `Materials` event; send it as journaled (deviation from EDMC, which synthesises one because it can miss it; record in a comment)
  - `check_key(commander_name: str, key: str) -> bool` — POST an empty `message: "[]"` batch; True when reply `msgnum` is 1xx. Synchronous; called from a worker.
  - `class EdsmPusher(commander_name: str, key: str, software: str, version: str, on_status: Callable[[str], None])` with `start()`, `stop()`, `set_game(gameversion: str, gamebuild: str)`, `submit(evt_with_transient: dict) -> None`
- Behaviour inside the worker thread:
  - first: GET discard list once (retry every 60 s until it arrives; hold events meanwhile); never send discarded names; keep `Docked` even if listed (EDMC does)
  - append to `pending`; when `should_send(pending, evt["event"], newgame_docked)` → POST form `commanderName`, `apiKey`, `fromSoftware`, `fromSoftwareVersion`, `fromGameVersion`, `fromGameBuild`, `message` (`json.dumps(pending, ensure_ascii=False)`)
  - reply: `msgnum // 100 == 1` → clear pending, status "EDSM: sent N events"; `== 2` → log + drop, status "EDSM: refused (msgnum)"; `== 5` → keep pending, retry next send; HTTP 429 → wait until the reset time from the response headers, then retry
  - `stop()` flushes pending once (EDMC sends on close)

- [ ] **Step 1: Write failing tests** — at minimum:

```python
def test_should_send_docked_always(): assert should_send([{"event": "Docked"}], "Docked", False)
def test_should_send_skips_moduleBuy_alone(): assert not should_send([{"event": "ModuleBuy"}], "ModuleBuy", False)
def test_should_send_cargo_after_newgame_docked(): assert not should_send([{"event": "Cargo"}], "Cargo", True)
def test_transient_fields(): ...            # keys _systemName/_systemCoordinates/_stationName/_shipId present, original evt unchanged
def test_discarded_event_not_sent(): ...    # discard ["Music"] → POSTed message has no "Music"
def test_batch_posts_form_fields(): ...     # FSDJump triggers POST; form has the 7 field names above; message is a JSON array
def test_msgnum_5xx_keeps_pending(): ...    # reply {"msgnum": 500} → next POST resends the same events
def test_msgnum_2xx_drops(): ...            # reply {"msgnum": 201} → next POST does not include them
def test_key_never_logged(caplog): ...      # key "secret-k" never in caplog.text on any failure path
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_edsm_push.py -q` → FAIL
- [ ] **Step 3: Implement** `edc/core/edsm_push.py`
- [ ] **Step 4: Run tests** → PASS; full suite → no new failures
- [ ] **Step 5: Commit** `feat: EDSM journal sender (EDMC rules)`

---

### Task 4: Settings, wiring, live confirmation

**Files:**
- Modify: `edc/config.py` (dataclass fields, `load`, `save`)
- Modify: `edc/ui/main_window.py` (settings tab next to `eddn_contribute_check` ~L3150; lifecycle next to `eddn_publisher.start()` ~L2608 / `.stop()` ~L3672; dispatch next to the EDDN block ~L4355)
- Test: `tests/test_push_wiring.py`, extend a `tests/test_config_*.py`

**Interfaces:**
- Consumes: Task 1 `save_key/load_key/clear_key`, Task 2 `RavenColonialPusher`, `check_key`, Task 3 `EdsmPusher`, `check_key`, `with_transient`
- Produces (config): `raven_push_enabled: bool = False`, `edsm_push_enabled: bool = False`, `edsm_commander_name: str = ""`

- [ ] **Step 1: Write failing tests**

```python
def test_config_push_defaults_off(tmp_path): ...  # fresh load → both False, edsm_commander_name == ""
def test_config_push_round_trip(tmp_path): ...    # save True/True/"Bob" → load returns same
def test_no_push_during_replay(): ...             # _replaying True + both enabled → pushers' submit not called
def test_no_push_for_other_commander(): ...       # state.commander "Alt" vs key name "B0B R0GERS" → submit not called
def test_push_when_live_and_matching(): ...       # live, matching → raven submit gets the depot event; edsm submit gets with_transient(evt)
```

Test the dispatch as a small helper method on the window (`_push_third_party(evt)`) called right after the EDDN block, so it can be unit-tested with fake pushers; follow how existing `tests/test_*` exercise main-window helpers.

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Config fields** in `AppConfig`, `load` (`bool(data.get(..., False))`, `str(... or "")`), `save`
- [ ] **Step 4: Settings UI** — a "Sharing" `QGroupBox` with the app's existing widget style:
  - Raven Colonial: checkbox "Send build progress and my deliveries to Raven Colonial", key `QLineEdit` (`EchoMode.Password`, placeholder "API key from ravencolonial.com/user"), Save, Test, status `QLabel`
  - EDSM: checkbox "Send my journal to EDSM (like the EDMC EDSM plugin)", EDSM commander name `QLineEdit`, key `QLineEdit` (password, placeholder "API key from edsm.net/settings/api"), Save, Test, status `QLabel`
  - Save: Raven runs `check_key` in a worker; on a name → `save_key(db, RAVEN, name, key)`, status "Linked to CMDR <name>"; on None → status "Key not accepted", nothing saved. EDSM: `check_key` in a worker; True → `save_key(db, EDSM, state.commander, key)`. Key field cleared after save; never re-filled.
  - Undecryptable stored key (`load_key` None while a row exists) → status "Saved key can't be read on this PC, enter it again"
  - Workers for Test/Save: kept as attributes for the window's lifetime (CLAUDE.md QThread rule), results back via signals.
- [ ] **Step 5: Lifecycle** — on start and whenever a switch/key changes: stop the old pusher, `load_key`, start a new one only if enabled and a key loads. Stop both at shutdown next to `eddn_publisher.stop()`. Feed `EdsmPusher.set_game` from `Fileheader`/`LoadGame` `gameversion`/`build`.
- [ ] **Step 6: Dispatch** `_push_third_party(evt)` after the EDDN block: return if `self._replaying`; Raven: enabled, pusher running, `state.commander == key name`, event is depot/contribution → `submit(evt, state.system_address)`; EDSM: enabled, running, `state.commander == key name` → `submit(with_transient(evt, state.system, (x, y, z), state.station_name, state.ship_id))`.
- [ ] **Step 7: Run tests** → PASS; full suite → no new failures
- [ ] **Step 8: Run the app** (no `QT_QPA_PLATFORM=offscreen`), open Settings, screenshot the Sharing group; confirm it renders and both switches start off.
- [ ] **Step 9: Commit** `feat: Sharing settings for Raven Colonial and EDSM pushes`
- [ ] **Step 10: Live confirmation with Evan (issue stays open until he confirms):** one depot dock → build page "still needed" matches the depot; one delivery → amount appears under his name on the build page; one jump → appears in his EDSM flight log. Also confirm whether Raven writes need `rcc-key` (spec "Unverified").
