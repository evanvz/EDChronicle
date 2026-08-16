# EDDN Fleet Carrier Reciprocity (Outbound) — Design

## Context

EDChronicle already listens for two Fleet-Carrier-relevant EDDN schemas
(`commodity/3` and `fcmaterials_journal/1`, the latter powering the
Engineering tab's "SOLD BY CARRIERS" search, recently extended with a
docking-access filter) but its own outbound contribution
(`edc/core/eddn_publisher.py`) has two gaps, both confirmed by direct code
read:

1. `build_commodity_message()` (publishes any docked market's `Market.json`,
   including the player's own Fleet Carrier) never includes the optional
   `carrierDockingAccess` field — even though the app tracks the player's
   own carrier's access (`state.carrier_docking_access`,
   `edc/core/state.py:199`) and `state.carrier_owned_market_id`
   (`edc/core/state.py:214`, "Confirmed-owned carrier's market/carrier ID"
   — distinct from a squadron carrier a member can also see `CarrierStats`
   for).
2. `FCMaterials.json` (the player's own carrier's material listings) is
   never read or published at all — confirmed via a repo-wide grep, zero
   production code references `FCMaterials`. So even though EDChronicle
   consumes everyone else's `fcmaterials_journal` sightings, its own
   carrier never appears in anyone else's equivalent search.

Both schemas verified directly against EDCD/EDDN's schema repository for
this design (not assumed):

- `commodity/3`'s `carrierDockingAccess` is a plain optional string field
  on the message object — no additional constraints found.
- `fcmaterials_journal/1`'s message requires exactly `timestamp`, `event`
  (literal `"FCMaterials"`), `MarketID`, `CarrierName`, `CarrierID`,
  `Items[]`, with `additionalProperties: false`. Each `Items[]` entry
  requires exactly `id` (integer, lowercase — confirmed via the schema's
  own property list, distinct from the capitalized `Name`/`Price`/`Stock`/
  `Demand`), `Name`, `Price`, `Stock`, `Demand` — no `Category`,
  `Category_Localised`, or `Name_Localised`, matching this app's own
  already-consumed shape in `edc/core/eddn_market.py::on_fcmaterials_message()`.

## Design

### 1. `carrierDockingAccess` on outbound `commodity/3`

`edc/core/eddn_publisher.py::build_commodity_message()` gains an optional
parameter:

```python
def build_commodity_message(data: Dict[str, Any], docking_access: Optional[str] = None) -> Optional[Dict[str, Any]]:
```

After the existing message dict is built (currently the `return {...}`
at the end of the function), if `docking_access` is a non-empty string,
add it: `msg["carrierDockingAccess"] = docking_access`.

`EddnPublisher.maybe_publish_commodity()` gains the same optional
parameter, threaded straight through to `build_commodity_message()`.

Call site — `edc/ui/main_window.py`'s `"Market"` event handler (currently
lines 2103-2110) — passes it only when the market being published is
confirmed the player's own carrier:

```python
docking_access = None
if market_data.get("MarketID") == getattr(self.state, "carrier_owned_market_id", None):
    docking_access = getattr(self.state, "carrier_docking_access", None)
self.eddn_publisher.maybe_publish_commodity(market_data, docking_access)
```

Never populated for a third-party carrier — the app has no way to know
another commander's carrier access when merely visiting it, only its own.

### 2. Publish `FCMaterials.json` as `fcmaterials_journal/1`

**New reader** — `edc/ui/main_window.py`, a new method
`_load_current_fcmaterials()` mirroring the existing
`_load_current_market()` (currently lines 657-677) exactly: reads
`FCMaterials.json` from `self.cfg.journal_dir`, returns the parsed dict or
`None` on any failure (missing file, malformed JSON), logged the same way.
Nothing is stored on `state` — this read exists solely to feed the
outbound publish, not to add any new local "my carrier's materials"
display (out of scope).

**New builder** — `edc/core/eddn_publisher.py::build_fcmaterials_message(data)`,
structured like `build_commodity_message()`: validates `MarketID` (int),
`CarrierName`/`CarrierID`/`timestamp` (non-empty strings), and `Items`
(list) are present; builds an explicit-allowlist `Items` array (`id`,
`Name`, `Price`, `Stock`, `Demand` only, each type-checked, dropping and
counting malformed entries the same way `build_commodity_message` does),
returns `None` if any top-level field is missing or no valid items remain.
Returned message dict:

```python
{
    "timestamp": data["timestamp"],
    "event": "FCMaterials",
    "MarketID": data["MarketID"],
    "CarrierName": data["CarrierName"],
    "CarrierID": data["CarrierID"],
    "Items": items,
}
```

**New publish method** — `EddnPublisher.maybe_publish_fcmaterials(data)`,
structured identically to `maybe_publish_commodity()` (same
`_is_beta`/`_commander` guards, same queue-based send), using a new
`_FCMATERIALS_SCHEMA_REF = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"`
constant (matching the URL pattern already established for
`_SCHEMA_REF`/`_COMMODITY_SCHEMA_REF`, and the prefix already used for
listening in `edc/core/eddn_listener.py`).

**Call site** — `edc/ui/main_window.py`'s event dispatch, a new branch
alongside the existing `"Market"` handling:

```python
if name == "FCMaterials":
    fc_data = self._load_current_fcmaterials()
    if fc_data and getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
        self.eddn_publisher.maybe_publish_fcmaterials(fc_data)
```

Same opt-in (`eddn_contribute_enabled`) and historical-replay guard
(`_replaying`) as every other publish path — no new setting, no new
config surface.

## Out of scope

- No new local display of the player's own carrier's material stock —
  this design only reads `FCMaterials.json` to republish it, nothing is
  persisted to `state` or shown in any panel.
- No publishing of a squadron-shared carrier's docking access or
  materials, even though `state.squadron_carrier` exists — only the
  player's confirmed-own carrier (`carrier_owned_market_id`) is covered,
  keeping the trust boundary simple (we only assert facts about the
  carrier we actually own).
- No change to the listening side (`eddn_market.py`/`eddn_listener.py`) —
  this design is outbound-only. (Listening for `Scan`/`SAASignalsFound`
  from EDDN is a separate, larger design already split out per the user's
  own decomposition decision — not part of this spec.)
- No new EDDN schema beyond the two already-listened-to ones — this is
  purely closing the gap between "what we consume" and "what we publish"
  for schemas already integrated.
