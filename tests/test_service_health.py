"""Tests for edc.core.service_health -- a passive logging.Handler that
tracks WARNING+ records from known EDSM/EDDN/tick loggers and reports a
simple ok/issue status per service, based on a 3-failures-in-10-minutes
threshold. Uses the module's internal recording function directly with
controlled timestamps for the threshold-logic tests (avoids mocking
time.monotonic across the whole test), plus one end-to-end test going
through real logging.warning() calls to confirm the handler is actually
wired up correctly."""
import logging

import pytest

from edc.core import service_health


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test gets a clean slate -- the module's tracking state is a
    module-level singleton (by design, so main_window.py doesn't need to
    thread an instance through anywhere), so tests must reset it."""
    service_health._reset_for_tests()
    yield
    service_health._reset_for_tests()


def test_no_records_means_ok():
    assert service_health.status("EDSM") == "ok"
    assert service_health.detail("EDSM") == ""


def test_below_threshold_stays_ok():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    assert service_health.status("EDSM") == "ok"


def test_three_failures_within_window_trips_issue():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"


def test_failures_across_different_edsm_modules_aggregate_to_one_service():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_powerplay", now + 1)
    service_health._record("edc.core.colonisation_eligibility", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"


def test_failures_outside_window_do_not_count():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    # Query 11 minutes later -- all three have aged out of the 10-minute window.
    assert service_health.status("EDSM", _now=now + 11 * 60) == "ok"


def test_services_are_independent():
    now = 1000.0
    service_health._record("edc.core.edsm_faction_lookup", now)
    service_health._record("edc.core.edsm_faction_lookup", now + 1)
    service_health._record("edc.core.edsm_faction_lookup", now + 2)
    assert service_health.status("EDSM", _now=now + 2) == "issue"
    assert service_health.status("EDDN", _now=now + 2) == "ok"
    assert service_health.status("BGS Tick", _now=now + 2) == "ok"


def test_detail_names_worst_offending_logger():
    now = 1000.0
    service_health._record("edc.core.edsm_powerplay", now)
    service_health._record("edc.core.edsm_powerplay", now + 1)
    service_health._record("edc.core.edsm_powerplay", now + 2)
    service_health._record("edc.core.edsm_faction_lookup", now + 3)
    d = service_health.detail("EDSM", _now=now + 3)
    assert "edsm_powerplay" in d
    assert "3" in d


def test_unknown_service_name_is_ok_not_an_error():
    assert service_health.status("NotARealService") == "ok"


def test_end_to_end_through_real_logging_call():
    """Confirms the handler is actually wired up to intercept real
    logging.warning() calls, not just that the internal recording
    function works in isolation."""
    service_health.attach()
    logger = logging.getLogger("edc.core.edsm_faction_lookup")
    for _ in range(3):
        logger.warning("simulated EDSM failure")
    assert service_health.status("EDSM") == "issue"


def test_info_level_records_are_ignored():
    service_health.attach()
    logger = logging.getLogger("edc.core.edsm_faction_lookup")
    for _ in range(5):
        logger.info("this is not a failure")
    assert service_health.status("EDSM") == "ok"


def test_unmapped_logger_is_ignored():
    service_health.attach()
    logger = logging.getLogger("edc.core.some_unrelated_module")
    for _ in range(5):
        logger.warning("unrelated warning")
    assert service_health.status("EDSM") == "ok"
    assert service_health.status("EDDN") == "ok"


def test_attach_is_idempotent():
    service_health.attach()
    service_health.attach()
    service_health.attach()
    handler_count = sum(
        1 for h in logging.getLogger().handlers
        if isinstance(h, service_health.ServiceHealthHandler)
    )
    assert handler_count == 1
