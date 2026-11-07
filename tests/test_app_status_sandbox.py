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


def test_blocked_exception_records_are_not_errors():
    recs = capture_errors()
    try:
        raise OutboundBlocked("app_status: outbound blocked ('1.2.3.4', 443)")
    except OutboundBlocked:
        logging.getLogger("edc.core.colonisation_eligibility").exception("lookup failed")
    assert recs == []


def test_dns_is_blocked_except_loopback():
    orig = socket.getaddrinfo
    counter = block_network()
    with pytest.raises(OutboundBlocked):
        socket.getaddrinfo("example.com", 80)
    assert counter["attempts"] == 1 and counter["hosts"] == {"example.com"}
    assert socket.getaddrinfo("localhost", 80)
    assert counter["attempts"] == 1
    unblock_network()
    assert socket.getaddrinfo is orig


def test_loopback_connect_is_not_counted():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    counter = block_network()
    try:
        with socket.create_connection(srv.getsockname(), timeout=2):
            pass
        c = socket.socket()
        c.connect(srv.getsockname())
        c.close()
        a, b = socket.socketpair()
        a.close()
        b.close()
    finally:
        srv.close()
    assert counter["attempts"] == 0


def test_blocked_note_names_check_and_hosts():
    from tools.app_status.sandbox import blocked_note
    counter = {"attempts": 12, "hosts": {f"h{i:02}" for i in range(12)}}
    assert blocked_note("replay", counter) == ("replay: outbound senders disabled; 12 connection attempts blocked ("
                                               + ", ".join(f"h{i:02}" for i in range(10)) + ")")
    assert blocked_note("app start", {"attempts": 0, "hosts": set()}) == \
        "app start: outbound senders disabled; 0 connection attempts blocked"


def test_app_start_logged_errors_are_start_findings(monkeypatch):
    from tools.app_status import sandbox

    def fake_build(app_dir, journal_dir):
        for _ in range(2):
            logging.getLogger("edc.core.galnet_news").error("bad thing")
        raise RuntimeError("no window")

    monkeypatch.setattr(sandbox, "build_window", fake_build)
    r = sandbox.check_app_start(ROOT)
    hits = [f for f in r["findings"] if f["text"] == "edc.core.galnet_news: bad thing (x2)"]
    assert hits and hits[0]["severity"] == "start" and hits[0]["area"] == "Overview/HUD"
