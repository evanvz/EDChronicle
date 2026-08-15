# Farming Guide Precise Live Matching — Design

## Context

The Intel tab's "FARMING LOCATIONS — THIS SYSTEM" card
(`edc/ui/panels/intel_panel.py`) surfaces two kinds of farming-guide
matches for the current system: exact system-name matches
(`FarmingLocations.get_for_system()`, unrelated and already correct) and
live-BGS-state matches (`_entry_matches_system()`).

The live-state path is a free-text keyword search: it lowercases each
guide entry's `name`+`method` and checks for substring hits per live tag
(`boom`/`war`/`outbreak`/`anarchy`/`low_security`/`pirate_attack`).
Confirmed by direct investigation, this produces real false positives and
one real false negative:

- **"HGE Pharmaceutical Isolators"** (encoded domain) contains "hge"/
  "high grade" in its text, so it fires on the `boom` tag — but its
  method text explicitly says "Outbreak systems," and its one material
  (Pharmaceutical Isolators) is Outbreak-specific, not Boom.
- **"High Wake Scans"** (encoded domain) fires on the `anarchy` tag via
  an accidental "wake scan" keyword hit — its actual method ("busy
  systems near stations/engineer hubs") has nothing to do with Anarchy
  government at all.
- **"Combat / CZ / bounty cleanup"** (manufactured) also fires on
  `low_security` via a coincidental "low" hit from "Low CZs" — not a
  real Low Security System reference.
- **"Pirate Attack settlements"** (odyssey_onfoot) explicitly names
  Pirate Attack, Civil Unrest, War, and Infrastructure Failure in its
  own method text, but `_get_system_opportunities()` doesn't produce
  `civil_unrest`/`infrastructure_failure` tags at all yet — a false
  negative, this entry can currently never match on 2 of its 4 real
  conditions.
- **"High Grade Emissions (HGE)"** (manufactured) is the entry that
  started this investigation: it has no `key_materials`, only an
  `examples[]` list of 5 `{material, state}` pairs — and `examples[]`
  is never rendered anywhere. Today, when this entry matches (any Boom
  faction), the card shows the domain badge, name, and generic method
  text — zero material-level information. The 5 examples span 4
  different live conditions (Outbreak, War/Civil War, Boom, and 2
  allegiance-based ones), so showing the whole entry as one match is
  wrong for the 4/5 examples that don't apply to whatever specific
  condition triggered the match.

Two of HGE's 5 examples (Imperial Shielding, Core Dynamics Composites)
require Empire/Federation allegiance — a signal `_get_system_opportunities()`
doesn't produce today, even though `state.system_allegiance` is already
read into a local variable there and left unused.

User confirmed scope: fix the whole live-matching mechanism (not just
HGE), by curating explicit tags into the guide data itself rather than
guessing from free text. Voice announcements for live farming matches are
explicitly deferred to a separate future pass — no voice hook exists for
this today, and it needs its own design (trigger event, anti-spam), out
of scope here.

## Design

### 1. `_get_system_opportunities()` — 4 new tags

Add to the existing tag-building logic in `edc/ui/panels/intel_panel.py`:

- `civil_unrest` — from `"civilunrest" in s` (mirrors the existing
  `"pirate" in s` → `pirate_attack` pattern).
- `infrastructure_failure` — from `"infrastructurefailure" in s`.
- `empire` — from `"empire" in alleg` (the existing, currently-unused
  `alleg` local variable).
- `federation` — from `"federation" in alleg`.

No other change to this function — the existing government/security/
economy tags (`anarchy`, `low_security`, `high_tech`, `military`,
`industrial`) and existing state tags (`boom`, `war`, `outbreak`,
`pirate_attack`, `election`, `expansion`) are untouched.

### 2. Guide data — explicit `state_tags`

Add a `"state_tags": [...]` array to the 6 entries in
`settings/elite_farming_locations.json` that can currently trigger a
live match (found by checking every entry against every existing
keyword bucket — no other entry in the guide is reachable via
`_entry_matches_system()` today):

| Entry | Domain | `state_tags` |
|---|---|---|
| High Wake Scans | encoded | *(omit the field — never live-matches)* |
| HGE Pharmaceutical Isolators | encoded | `["outbreak"]` |
| Combat / CZ / bounty cleanup | manufactured | `["war", "pirate_attack"]` |
| Pirate Attack settlements | odyssey_onfoot | `["pirate_attack", "war", "civil_unrest", "infrastructure_failure"]` |
| Anarchy-government systems | odyssey_onfoot | `["anarchy"]` |
| Power Generator Reactivation missions | odyssey_onfoot | `["war"]` |

"High Grade Emissions (HGE)" (manufactured) gets no hand-curated
`state_tags` — its matching is derived automatically from its own
`examples[]` (see §4). Every other entry in the guide has no
`state_tags` field and is therefore only ever reachable via exact
system-name matching, never live-tag matching — this is the correct,
conservative default: an entry with no curated tag makes no live claim
at all, rather than falling back to guessing.

### 3. `FarmingLocations` loader

`edc/core/farming_locations.py`'s `_load()` normalizes each record's
core fields (`name`, `system`, `body`, `method`, `key_materials`). Add
`state_tags` to that normalization: read `rec.get("state_tags")`, keep
it only if it's a non-empty list of strings (lowercased), attach as
`out["state_tags"]`. Absent/invalid input simply omits the key — no
behavior change to indexing (`_by_system`/`_by_material` untouched).

### 4. Matching — `_entry_matches_system()` replaced

Delete the current keyword-search implementation. Replace with:

```python
def _entry_matches_system(self, loc, tags):
    """
    Returns the subset of `tags` this entry actually matches, driven
    by curated data (loc["state_tags"], or -- for entries with an
    examples[] list -- each example's own state, mapped to tags) --
    never free-text keyword guessing. Empty set means no live match
    (the entry may still appear via an exact system/body name match,
    a separate, unrelated path).
    """
    examples = loc.get("examples")
    if isinstance(examples, list) and examples:
        matched_tags = set()
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            matched_tags |= self._state_text_to_tags(ex.get("state") or "") & tags
        return matched_tags

    entry_tags = set(loc.get("state_tags") or [])
    return entry_tags & tags
```

New helper `_state_text_to_tags(state_text)` maps an `examples[].state`
free-text value to the tag vocabulary (this is the ONE place free-text
mapping still happens, scoped to the 5 known HGE example strings —
not a general-purpose parser):

```python
_STATE_TEXT_TAG_MAP = {
    "outbreak": {"outbreak"},
    "boom": {"boom"},
}

def _state_text_to_tags(self, state_text: str) -> set:
    s = state_text.lower()
    tags = set()
    for key, mapped in self._STATE_TEXT_TAG_MAP.items():
        if key in s:
            tags |= mapped
    if "war" in s or "civil war" in s:
        tags.add("war")
    if "imperial" in s:
        tags.add("empire")
    if "federal" in s:
        tags.add("federation")
    return tags
```

Callers (`refresh()`'s `state_matches` list-building) change from
`if self._entry_matches_system(r, opportunities)` to checking the
returned set is non-empty, and — for entries with `examples[]` — carry
the matched tag set alongside the entry so the renderer knows which
examples to show (§5).

### 5. Rendering — show only matched examples

`refresh()` currently builds `state_matches` as a flat list of raw
entry dicts. Change: when an entry has `examples[]`, don't pass the raw
entry — build a shallow copy with a new `_matched_examples` key
containing only the examples whose own tags intersected the live tags:

```python
matched_tags = self._entry_matches_system(r, opportunities)
if not matched_tags:
    continue
entry = r
if isinstance(r.get("examples"), list):
    entry = dict(r)
    entry["_matched_examples"] = [
        ex for ex in r["examples"]
        if isinstance(ex, dict)
        and self._state_text_to_tags(ex.get("state") or "") & opportunities
    ]
state_matches.append(entry)
```

`_farm_entry_html()` gains a new rendering branch, checked before the
existing `key_materials`/`sites` block: if `loc.get("_matched_examples")`
is present, render each matched example as its own line (material name
+ its state, e.g. "Pharmaceutical Isolators — Outbreak") instead of the
generic method line. If `key_materials`/`sites` are also present on the
same entry (not the case for HGE today, but keep the branches
independent rather than mutually exclusive, so future guide entries can
combine both without a rendering gap).

### Testing

- `_get_system_opportunities()`: 4 new synthetic cases (civil_unrest,
  infrastructure_failure, empire, federation tag production), matching
  this file's existing test conventions for the function if any exist
  — otherwise a direct unit test importing `IntelPanel` is fine since
  this is a pure function of `state`, no Qt event loop needed.
- `_entry_matches_system()`: replace any existing keyword-search tests
  with tests against the new `state_tags`/`examples` logic — cases:
  entry with matching `state_tags` → non-empty set; entry with no
  `state_tags` and no `examples` → empty set always (never guesses);
  HGE-shaped entry with `examples` → only the tags whose example state
  is actually live-tagged are returned, not all 5.
- `_state_text_to_tags()`: direct unit tests for the 5 known HGE
  example strings ("Outbreak", "Imperial allegiance / any state",
  "Federal allegiance / any state", "War / Civil War", "Boom") plus an
  unrecognized string returning an empty set (no silent false match).
- Rendering (`_farm_entry_html` with `_matched_examples`): verified
  visually/live, matching this codebase's established convention for
  panel-rendering (no automated test elsewhere in `intel_panel.py`).
- Guide data: after editing `elite_farming_locations.json`, confirm it
  still parses (`json.load`) and `FarmingLocations` still loads without
  error — no new automated test needed for static content, matches how
  the two earlier same-file edits this session were verified.

## Out of scope

- Voice announcement for live farming matches — no hook exists today;
  deferred to a separate future pass per user's explicit choice.
- Any entry in the guide beyond the 7 identified (6 curated +
  HGE-via-examples) — every other entry has no live-match path today
  and none is being added for it.
- `get_for_system()`/exact system-name matching — unrelated, already
  correct, untouched.
