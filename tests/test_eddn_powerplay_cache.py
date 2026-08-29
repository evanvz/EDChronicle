"""EddnPowerPlayCache.get_controller() must be able to report "no longer
controlled", not just accumulate old controller sightings forever -- the
listener now emits power="" for a genuine Unoccupied sighting (previously
dropped entirely), and get_controller() must treat it as real data, not a
missing entry."""
from edc.core.eddn_powerplay import EddnPowerPlayCache


def _cache(tmp_path):
    return EddnPowerPlayCache(tmp_path)


def test_no_controller_sighting_is_stored_and_returned(tmp_path):
    cache = _cache(tmp_path)
    cache.ingest(12345, power="", power_state="Unoccupied", timestamp="2026-08-20T10:00:00Z")

    rec = cache.get_controller(12345)
    assert rec is not None
    assert rec["power"] == ""
    assert rec["power_state"] == "Unoccupied"


def test_fresher_no_controller_sighting_wins_over_older_controller_sighting(tmp_path):
    cache = _cache(tmp_path)
    cache.ingest(12345, power="Yuri Grom", power_state="Exploited", timestamp="2026-08-10T10:00:00Z")
    cache.ingest(12345, power="", power_state="Unoccupied", timestamp="2026-08-20T10:00:00Z")

    rec = cache.get_controller(12345)
    assert rec["power"] == ""
    assert rec["power_state"] == "Unoccupied"


def test_stale_no_controller_sighting_loses_to_fresher_controller_sighting(tmp_path):
    cache = _cache(tmp_path)
    cache.ingest(12345, power="", power_state="Unoccupied", timestamp="2026-08-10T10:00:00Z")
    cache.ingest(12345, power="Yuri Grom", power_state="Exploited", timestamp="2026-08-20T10:00:00Z")

    rec = cache.get_controller(12345)
    assert rec["power"] == "Yuri Grom"
