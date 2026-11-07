import logging
import socket
from pathlib import Path

import pytest

from tools.app_status.sandbox import (
    OutboundBlocked, block_network, unblock_network, make_app_dir, capture_errors, release_errors)

ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _restore():
    yield
    unblock_network()
    release_errors()


def test_block_network_counts_and_raises():
    counter = block_network()
    with pytest.raises(OutboundBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
    assert counter["attempts"] == 1


def test_sandbox_never_copies_user_settings(tmp_path):
    app_dir = make_app_dir(ROOT, tmp_path)
    assert not (app_dir / "settings" / "settings.json").exists()
    assert (app_dir / "settings" / "exo_values.json").exists()


def test_blocked_records_are_not_errors():
    recs = capture_errors()
    logging.getLogger("edc.core.galnet_news").error("fetch failed: app_status: outbound blocked example.com")
    logging.getLogger("edc.core.galnet_news").error("real failure")
    assert [r.getMessage() for r in recs] == ["real failure"]
