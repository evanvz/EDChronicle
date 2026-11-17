from edc.core.colonisation_plan_status import primary_depot, status_updates, unlinked_depots

SA = 100
PRIMARY = {"facility": "Coriolis", "body": "A 1", "location": "orbital", "slot_index": 0}


def depot(id_, market_id, complete=0, sa=SA):
    return {"id": id_, "market_id": market_id, "system_address": sa,
            "station_name": "x", "progress": 0.0, "complete": complete, "resources": []}


def row(market_id=None, status="Planned", body="A 1", location="orbital", slot_index=0, facility="Outpost"):
    return {"facility": facility, "body": body, "location": location,
            "slot_index": slot_index, "status": status, "market_id": market_id}


def test_first_depot_becomes_building_primary():
    out = status_updates([], [depot(1, 11)], SA, PRIMARY)
    assert out == [{**PRIMARY, "status": "Building", "market_id": 11}]


def test_primary_turns_complete_when_depot_completes():
    out = status_updates([], [depot(1, 11, 1)], SA, PRIMARY)
    assert out[0]["status"] == "Complete"


def test_manual_status_on_unlinked_row_untouched():
    stored = [row(None, "Building", slot_index=3)]
    assert status_updates(stored, [], SA, PRIMARY) == []


def test_linked_site_turns_complete():
    stored = [row(11, "Building", slot_index=2), row(12, "Complete", slot_index=3)]
    out = status_updates(stored, [depot(1, 10), depot(2, 11, 1), depot(3, 12, 1)], SA, PRIMARY)
    assert [r for r in out if r["slot_index"] == 2] == [{**stored[0], "status": "Complete"}]
    assert not [r for r in out if r["slot_index"] == 3]


def test_other_systems_depots_ignored():
    assert status_updates([], [depot(1, 11, sa=999)], SA, PRIMARY) == []
    assert primary_depot([depot(1, 11, sa=999)], SA) is None
    assert unlinked_depots([], [depot(1, 11, sa=999)], SA) == []


def test_second_depot_is_unlinked_not_auto_linked():
    depots = [depot(2, 22), depot(1, 11, 1)]
    out = status_updates([], depots, SA, PRIMARY)
    assert [r["market_id"] for r in out] == [11]
    assert [d["market_id"] for d in unlinked_depots(out, depots, SA)] == [22]


def test_stored_primary_without_depot_gets_linked():
    stored = [row(None, "Planned", facility="Planetary Port")]
    out = status_updates(stored, [depot(1, 11)], SA, PRIMARY)
    assert out == [{**stored[0], "market_id": 11, "status": "Building"}]
    out = status_updates(stored, [depot(1, 11, 1)], SA, PRIMARY)
    assert out[0]["status"] == "Complete" and out[0]["facility"] == "Planetary Port"


def test_body_links_take_the_first_open_surface_step_on_the_sites_body():
    # Evan 2026-11-16: the plan knows the body, so a docked site links to its step by itself.
    from edc.core.colonisation_plan_status import body_links
    step = lambda n, body, slot, status="Planned", loc="surface": {
        "n": n, "facility": "mining", "body": body, "location": loc, "slot_index": slot, "status": status}
    steps = [step(1, "HIP 1 A 1", 0, loc="orbital"), step(2, "HIP 1 A 4 a", 0, "Complete"),
             step(3, "HIP 1 A 4 a", 1), step(4, "HIP 1 A 3 b", 0)]
    site = lambda id_, market, body, complete=0, removed=0: {
        **depot(id_, market, complete), "body_name": body, "removed": removed}
    depots = [site(1, 10, None), site(2, 20, "hip 1 a 4 a"), site(3, 30, "HIP 1 A 3 b", 1, 1),
              site(4, 40, "HIP 1 A 3 b", 0, 1), site(5, 50, "HIP 1 A 9")]
    out = body_links(steps, [], depots, SA)
    assert [(u["body"], u["slot_index"], u["status"], u["market_id"]) for u in out] == [
        ("HIP 1 A 4 a", 1, "Building", 20),   # the finished slot 0 is skipped
        ("HIP 1 A 3 b", 0, "Complete", 30)]   # removed but complete still counts; removed unfinished does not
    # Linked sites and taken steps are left alone.
    stored = [row(20, "Building", "HIP 1 A 4 a", "surface", 1)]
    assert [u["market_id"] for u in body_links(steps, stored, depots, SA)] == [30]
    assert [d["market_id"] for d in unlinked_depots(stored, depots, SA)] == [10, 50]
