"""Notable Stellar Phenomena Codex entries (e.g. Metallic Crystals in a
Lagrange cloud) are a single-scan confirmation via the Short Range
Composition Scanner -- not a hint toward the usual 3-sample Genetic
Sampler cycle used for planetary organisms. Confirmed via real journal
data: planetary organisms carry Latitude/Longitude and an empty
NearestDestination; NSP entities carry NearestDestination (e.g. "Notable
stellar phenomena") and no coordinates. Real EventEngine, matching this
repo's convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _codex_event(name_localised, nearest_destination="", body_id=1):
    return {
        "event": "CodexEntry",
        "BodyID": body_id,
        "Name_Localised": name_localised,
        "NearestDestination": nearest_destination,
        "NearestDestination_Localised": (
            "Notable stellar phenomena" if nearest_destination else ""
        ),
    }


def test_nsp_codex_entry_marked_complete(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_codex_event(
        "Purpureum Metallic Crystals",
        nearest_destination="$Fixed_Event_Life_Cloud;",
    ))
    rec = next(iter(engine.state.exo.values()))
    assert rec["IsPhenomena"] is True
    assert rec["Complete"] is True


def test_planetary_codex_entry_not_marked_complete(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_codex_event("Stratum Tectonicas - Green"))
    rec = next(iter(engine.state.exo.values()))
    assert rec["IsPhenomena"] is False
    assert rec["Complete"] is False


def test_nsp_codex_entry_gets_space_body_name_and_nonempty_variant(tmp_path):
    # "Purpureum Metallic Crystals" has no " - " separator, unlike planetary
    # organisms ("Species - Color") -- variant_txt must not end up empty, or
    # _save_exobiology_to_db()'s non-empty check silently drops the save.
    engine = _engine(tmp_path)
    engine.process(_codex_event(
        "Purpureum Metallic Crystals",
        nearest_destination="$Fixed_Event_Life_Cloud;",
    ))
    rec = next(iter(engine.state.exo.values()))
    assert rec["BodyName"] == "Space"
    assert rec["Variant"]
    assert rec["Species"]


def test_nsp_codex_entry_appends_exobiology_complete_message(tmp_path):
    # CodexEntry never goes through ScanOrganic's own completion messaging,
    # so without this a phenomena confirmation's Complete=True would never
    # trigger _save_exobiology_to_db() (that save is itself gated on this
    # exact message appearing in msgs).
    engine = _engine(tmp_path)
    _, msgs = engine.process(_codex_event(
        "Purpureum Metallic Crystals",
        nearest_destination="$Fixed_Event_Life_Cloud;",
    ))
    assert any(m.startswith("Exobiology complete: ") for m in msgs)

    # Second identical CodexEntry (Frontier can log the same one twice) must
    # not re-announce it.
    _, msgs2 = engine.process(_codex_event(
        "Purpureum Metallic Crystals",
        nearest_destination="$Fixed_Event_Life_Cloud;",
    ))
    assert not any(m.startswith("Exobiology complete: ") for m in msgs2)
