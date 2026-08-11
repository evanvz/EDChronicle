"""Regression test for EddnPowerPlayWorker._pump()'s stale-connection
watchdog. Reproduces a real bug found live: a ZMQ SUB socket's recv()
just keeps timing out (zmq.error.Again) forever when the connection has
silently died -- no exception, no signal, nothing to trigger the
existing reconnect logic. Confirmed live: our connection went quiet for
over an hour with zero errors logged, while a fresh connection to the
same relay pulled hundreds of messages in seconds. _pump() must now
give up and return (letting the caller reconnect) after too long
without a single successful recv()."""
import zlib
import json
import zmq

from edc.core.eddn_listener import EddnPowerPlayWorker
import edc.core.eddn_listener as eddn_listener


class _AlwaysTimesOutSocket:
    def recv(self):
        raise zmq.error.Again()


class _MessagesThenTimesOutSocket:
    """Yields `message_count` real messages, then times out forever --
    simulates a connection that was healthy and then went stale."""

    def __init__(self, message_count):
        self._remaining = message_count

    def recv(self):
        if self._remaining > 0:
            self._remaining -= 1
            payload = {"$schemaRef": "https://eddn.edcd.io/schemas/journal/1", "message": {"event": "Other"}}
            return zlib.compress(json.dumps(payload).encode("utf-8"))
        raise zmq.error.Again()


def test_pump_returns_after_stale_timeout_with_no_messages(monkeypatch):
    monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", 0)
    worker = EddnPowerPlayWorker()
    # threshold of 0 means the very first timeout already exceeds it --
    # confirms _pump returns instead of looping forever.
    worker._pump(_AlwaysTimesOutSocket())  # must return, not hang


def test_pump_does_not_go_stale_while_messages_are_arriving(monkeypatch):
    monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", 300)
    worker = EddnPowerPlayWorker()
    sock = _MessagesThenTimesOutSocket(message_count=5)

    # Real messages keep last_message_time fresh, so with a 300s threshold
    # and a socket that immediately times out with zmq.error.Again after
    # the messages run out (no real delay), _pump would spin forever
    # rather than returning -- stop it externally after a moment to prove
    # it processed the messages and was still trying, not stale.
    call_count = {"n": 0}
    real_recv = sock.recv

    def counting_recv():
        call_count["n"] += 1
        if call_count["n"] > 20:
            worker._stop = True
        return real_recv()

    sock.recv = counting_recv
    worker._pump(sock)  # returns only because we set _stop, not because stale
    assert call_count["n"] > 5  # consumed all 5 real messages, then kept trying
