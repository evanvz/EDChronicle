from __future__ import annotations
from typing import Any, Dict, List, Optional

# Category name (as used by MaterialCollected/MaterialDiscarded/MaterialTrade)
# -> (counts dict attr, localised dict attr) on GameState.
_CATEGORY_ATTRS = {
    "raw":          ("materials_raw",          "materials_raw_loc"),
    "manufactured": ("materials_manufactured",  "materials_manufactured_loc"),
    "encoded":      ("materials_encoded",       "materials_encoded_loc"),
}


def _adjust_material(engine, category: Optional[str], rec: Dict[str, Any], delta: int) -> None:
    """
    Apply a +/- delta to a single material's live count, keeping the
    matching *_loc display-name dict in sync. `category` is "Raw" /
    "Manufactured" / "Encoded" (case-insensitive) when known (Material-
    Collected/Discarded/Trade all provide it). When it's None (Engineer-
    Craft's Ingredients list doesn't tag category), the material is
    looked up by name across all three categories instead — raw/
    manufactured/encoded material names never overlap.
    """
    nm = rec.get("Name")
    if not isinstance(nm, str):
        return
    key = nm.strip().lower()
    if not key:
        return
    nl = rec.get("Name_Localised")
    display = nl.strip() if isinstance(nl, str) and nl.strip() else None

    cat_key = category.strip().lower() if isinstance(category, str) else None
    attrs = [_CATEGORY_ATTRS[cat_key]] if cat_key in _CATEGORY_ATTRS else list(_CATEGORY_ATTRS.values())

    for counts_attr, loc_attr in attrs:
        counts: Dict[str, int] = getattr(engine.state, counts_attr)
        if cat_key is None and key not in counts:
            continue  # searching all categories — only touch the one that already holds this material
        new_count = counts.get(key, 0) + delta
        if new_count > 0:
            counts[key] = new_count
        else:
            counts.pop(key, None)
        if display:
            getattr(engine.state, loc_attr)[key] = display
        return


def _adjust_backpack(engine, rec: Dict[str, Any], delta: int) -> None:
    """
    Apply a +/- delta to a single backpack material's live count, keeping
    the matching localised-name dict in sync -- same shape as
    _adjust_material() above, but backpack_items is one flat dict (no
    per-category split), so there's no category-attr lookup needed.
    """
    nm = rec.get("Name")
    if not isinstance(nm, str):
        return
    key = nm.strip().lower()
    if not key:
        return
    nl = rec.get("Name_Localised")
    display = nl.strip() if isinstance(nl, str) and nl.strip() else None

    counts = engine.state.backpack_items
    new_count = counts.get(key, 0) + delta
    if new_count > 0:
        counts[key] = new_count
    else:
        counts.pop(key, None)
    if display:
        engine.state.backpack_localised[key] = display


def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Inventory / commander state / load snapshots.
    Returns True if handled.
    """

    if name == "Commander":
        engine.state.commander = event.get("Name") or engine.state.commander
        engine.state.ship = event.get("Ship") or engine.state.ship
        engine.state.ship_id = event.get("ShipID") if isinstance(event.get("ShipID"), int) else engine.state.ship_id
        return True

    elif name == "LoadGame":
        # Some sessions emit this early; capture credits/ship basics if present.
        engine.state.commander = event.get("Commander") or engine.state.commander
        engine.state.ship = event.get("Ship") or engine.state.ship
        sid = event.get("ShipID")
        if isinstance(sid, int):
            engine.state.ship_id = sid
        ody = event.get("Odyssey")
        if isinstance(ody, bool):
            engine.state.odyssey = ody
        return True

    elif name == "Materials":
        raw = event.get("Raw")
        manufactured = event.get("Manufactured")
        encoded = event.get("Encoded")
        if raw is not None:
            engine.state.materials_raw, engine.state.materials_raw_loc = engine._parse_materials_category(raw)
        if manufactured is not None:
            engine.state.materials_manufactured, engine.state.materials_manufactured_loc = engine._parse_materials_category(manufactured)
        if encoded is not None:
            engine.state.materials_encoded, engine.state.materials_encoded_loc = engine._parse_materials_category(encoded)
        return True

    elif name == "ShipLocker":
        # Odyssey storage
        locker = event.get("Items")
        if locker is not None:
            engine.state.shiplocker_items, engine.state.shiplocker_localised = engine._parse_shiplocker_items(locker)
            engine.state.shiplocker_last_update = event.get("timestamp")
        return True

    elif name == "ModuleBuy":
        # Lightweight ledger entry
        mod = event.get("BuyItem")
        if isinstance(mod, str) and mod.strip():
            msgs.append(f"Module bought: {mod}")
        return True

    elif name == "Cargo":
        # Cargo inventory snapshot
        inv = event.get("Inventory")
        if isinstance(inv, list):
            engine.state.cargo_inventory = inv
        return True

    elif name == "MaterialCollected":
        _adjust_material(engine, event.get("Category"), event, +int(event.get("Count") or 0))
        return True

    elif name == "MaterialDiscarded":
        _adjust_material(engine, event.get("Category"), event, -int(event.get("Count") or 0))
        return True

    elif name == "MaterialTrade":
        paid = event.get("Paid")
        received = event.get("Received")
        if isinstance(paid, dict):
            _adjust_material(engine, paid.get("Category"), paid, -int(paid.get("Count") or 0))
        if isinstance(received, dict):
            _adjust_material(engine, received.get("Category"), received, +int(received.get("Count") or 0))
        return True

    elif name == "BackpackChange":
        for item in (event.get("Added") or []):
            if isinstance(item, dict):
                _adjust_backpack(engine, item, +int(item.get("Count") or 0))
        for item in (event.get("Removed") or []):
            if isinstance(item, dict):
                _adjust_backpack(engine, item, -int(item.get("Count") or 0))
        return True

    elif name == "EngineerCraft":
        for ingredient in (event.get("Ingredients") or []):
            if isinstance(ingredient, dict):
                _adjust_material(engine, None, ingredient, -int(ingredient.get("Count") or 0))
        return True

    return False