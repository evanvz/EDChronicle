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
