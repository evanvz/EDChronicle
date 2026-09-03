"""
Re-vendors EDChronicle's offline EDCD/FDevIDs snapshots from the live repo.

Covers the three settings/ files that are pure 1:1 FDevIDs conversions
(no other data blended in) -- ships, rare commodities, Odyssey
microresource names. engineering_blueprints.json/odyssey_engineering.json/
engineer_requirements.json blend in coriolis-data and other sources and
are NOT handled here; update those by hand.

Usage:
  python tools/update_fdevids.py            -- dry run: fetch + diff only
  python tools/update_fdevids.py --write    -- fetch, diff, and overwrite
  python tools/update_fdevids.py --only ships   -- just one file (ships|rare|micro)
"""
import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import requests

SETTINGS_DIR = Path(__file__).parent.parent / "settings"
_RAW_BASE = "https://raw.githubusercontent.com/EDCD/FDevIDs/master"
_TIMEOUT = 20


def _fetch_csv(filename: str) -> list[dict]:
    resp = requests.get(f"{_RAW_BASE}/{filename}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _build_ships() -> dict:
    rows = _fetch_csv("shipyard.csv")
    symbols = {
        row["symbol"].strip().lower(): {"name": row["name"].strip()}
        for row in rows if row.get("symbol") and row.get("name")
    }
    return {
        "source": "EDCD/FDevIDs shipyard.csv",
        "count": len(symbols),
        "symbols": dict(sorted(symbols.items())),
    }


def _build_rare_commodities() -> dict:
    # Deliberately NOT sorted -- "items" is a JSON list, so list order is
    # part of equality/diffing. The vendored file preserves the CSV's own
    # row order; re-sorting here would produce a large no-op diff on every
    # run purely from reordering, unlike "symbols"/"names" below which are
    # JSON objects (key order doesn't affect equality either way).
    rows = _fetch_csv("rare_commodity.csv")
    items = [
        {
            "symbol": row["symbol"].strip().lower(),
            "name": row["name"].strip(),
            "market_id": int(row["market_id"]) if row.get("market_id") else None,
            "category": row.get("category", "").strip(),
        }
        for row in rows if row.get("symbol") and row.get("name")
    ]
    return {"source": "EDCD/FDevIDs rare_commodity.csv", "items": items}


def _build_odyssey_material_names(existing: dict) -> dict:
    rows = _fetch_csv("microresources.csv")
    names = {
        row["symbol"].strip().lower(): row["English name"].strip()
        for row in rows if row.get("symbol") and row.get("English name")
    }
    return {
        "last_updated": existing.get("last_updated"),  # re-stamped in main() only if content actually changed
        "source": "EDCD/FDevIDs microresources.csv",
        "names": dict(sorted(names.items())),
    }


def _ships_keys(data: dict) -> set:
    return set(data.get("symbols", {}).keys())


def _rare_keys(data: dict) -> set:
    return {i["symbol"] for i in data.get("items", [])}


def _micro_keys(data: dict) -> set:
    return set(data.get("names", {}).keys())


# name -> (settings filename, builder, builder needs existing-file dict, key-extractor for diffing)
_TARGETS = {
    "ships": ("fdevids_ships.json", lambda _existing: _build_ships(), _ships_keys),
    "rare": ("rare_commodities.json", lambda _existing: _build_rare_commodities(), _rare_keys),
    "micro": ("odyssey_material_names.json", _build_odyssey_material_names, _micro_keys),
}


def _diff_and_report(name: str, path: Path, old_data: dict, new_data: dict, key_fn) -> bool:
    """Returns True if new_data differs from what's on disk."""
    old_keys = key_fn(old_data)
    new_keys = key_fn(new_data)
    added = new_keys - old_keys
    removed = old_keys - new_keys
    changed = new_data != old_data

    print(f"== {name} ({path.name}) ==")
    if not changed:
        print("  up to date, no changes")
        return False
    print(f"  {len(new_keys)} entries (was {len(old_keys)})")
    if added:
        print(f"  + added: {sorted(added)[:20]}{' ...' if len(added) > 20 else ''}")
    if removed:
        print(f"  - removed: {sorted(removed)[:20]}{' ...' if len(removed) > 20 else ''}")
    if not added and not removed:
        print("  same entries, field values differ (name/category/etc. changed)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Re-vendor EDChronicle's EDCD/FDevIDs snapshots.")
    parser.add_argument("--write", action="store_true", help="Overwrite settings/ files (default: dry run)")
    parser.add_argument("--only", choices=list(_TARGETS.keys()), help="Only update one file")
    args = parser.parse_args()

    targets = [args.only] if args.only else list(_TARGETS.keys())
    any_changed = False

    for key in targets:
        filename, builder, key_fn = _TARGETS[key]
        path = SETTINGS_DIR / filename
        old_text = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            old_data = json.loads(old_text) if old_text else {}
        except json.JSONDecodeError:
            old_data = {}

        try:
            new_data = builder(old_data)
        except requests.RequestException as exc:
            print(f"== {key} ({filename}) ==\n  FAILED to fetch: {exc}", file=sys.stderr)
            continue

        changed = _diff_and_report(key, path, old_data, new_data, key_fn)
        any_changed = any_changed or changed

        if changed and args.write:
            if "last_updated" in new_data:
                new_data["last_updated"] = date.today().isoformat()
            path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"  wrote {path}")

    if any_changed and not args.write:
        print("\nRun again with --write to apply these changes.")
    elif not any_changed:
        print("\nAll checked files are up to date.")


if __name__ == "__main__":
    main()
