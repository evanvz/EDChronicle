"""Exobiology's sample-distance requirement (CCR) must be measured against
every prior sample point, not just the most recent one -- confirmed live:
sample 3 needs to clear the minimum distance from BOTH sample 1 and sample
2, not just sample 2. The live Status-tick tracker (used while walking
toward the next sample) only checked the last point, so it could show
"distance reached" while still too close to an earlier sample -- which the
game's own scan then rejects. The ScanOrganic "sample" handler itself
already computed the correct min-distance-to-all-points; this test targets
the live tracker, which didn't. Real EventEngine, matching this repo's
convention (see test_footfall_tracking.py)."""
import math

from edc.core.event_engine import EventEngine
from edc.core.state import GameState

_KEY = "5|TestGenus|TestSpecies|"


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _status(body_name, lat, lon, radius=1000.0):
    return {
        "event": "Status", "BodyName": body_name,
        "Latitude": lat, "Longitude": lon, "PlanetRadius": radius,
    }


def _scan_organic(scan_type):
    return {
        "event": "ScanOrganic", "ScanType": scan_type,
        "Genus": "TestGenus", "Species": "TestSpecies", "Body": 5,
    }


def test_live_ccr_tracker_checks_all_prior_samples(tmp_path):
    # Journal mechanics: Log is sample 1 (progress 1/3), then two "Sample"
    # scans are samples 2 and 3 (progress 2/3, 3/3) -- matching the
    # journal_importer/event_engine convention (see the "Log = 1/3, Sample+
    # Sample = 2/3 and 3/3" comment a few lines above this handler).
    engine = _engine(tmp_path)
    engine.state.body_id_to_name[5] = "Test Body"

    engine.process(_scan_organic("Log"))  # sample 1
    engine.state.exo[_KEY]["CCRRequiredM"] = 100

    # Baseline at sample 1's position (lat 0).
    engine.process(_status("Test Body", 0.0, 0.0))

    # Walk far enough away (~200m on a 1000m-radius body) for sample 2.
    theta = 200.0 / 1000.0
    far_lat = math.degrees(theta)
    engine.process(_status("Test Body", far_lat, 0.0))
    assert engine.state.exo[_KEY]["CCRRemainingM"] == 0

    engine.process(_scan_organic("Sample"))  # sample 2, taken at far_lat

    # Walk back near sample 1's position -- far from sample 2, but right on
    # top of sample 1. The old "last point only" logic would report clear
    # (checks only sample 2, which is far); the correct check must still
    # show 100m remaining (checks sample 1 too, which is 0m away).
    engine.process(_status("Test Body", 0.0, 0.0))
    assert engine.state.exo[_KEY]["CCRRemainingM"] == 100
