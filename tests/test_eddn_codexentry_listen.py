"""Compliant senders put CodexEntry on codexentry/1, with no *_Localised names
(EDDN rejects those); the name comes from our own codex log by EntryID."""
from types import SimpleNamespace

from edc.core.eddn_market import EddnMarketCache


def test_codexentry_message_resolved_from_entry_id():
    repo = SimpleNamespace(get_codex_name=lambda eid: {2420201: "Stratum Paleas - Emerald"}.get(eid))
    cache = EddnMarketCache(repo)
    base = {"event": "CodexEntry", "Category": "$Codex_Category_Biology;", "SystemAddress": 42,
            "Name": "$Codex_Ent_Stratum_02_E_Name;", "timestamp": "2026-10-17T10:00:00Z"}
    cache.on_codex_entry_seen({**base, "BodyID": 7, "EntryID": 2420201})
    cache.on_codex_entry_seen({**base, "BodyID": 8, "EntryID": 9999999})          # not in our log: skipped
    assert [r[:3] for r in cache._codex_buffer.values()] == [(42, 7, "Stratum Paleas - Emerald")]


def test_listener_routes_codexentry_schema():
    import json, zlib
    from unittest.mock import MagicMock
    from edc.core.eddn_listener import EddnPowerPlayWorker
    w = EddnPowerPlayWorker()
    seen = []
    w.codex_entry_seen.connect(seen.append)
    msg = {"event": "CodexEntry", "Category": "$Codex_Category_Biology;", "SystemAddress": 42, "BodyID": 7,
           "EntryID": 2420201, "System": "X", "StarPos": [0, 0, 0], "timestamp": "2026-10-17T10:00:00Z"}
    raw = zlib.compress(json.dumps({"$schemaRef": "https://eddn.edcd.io/schemas/codexentry/1",
                                    "header": {}, "message": msg}).encode())
    sock = MagicMock()
    sock.recv.side_effect = [raw, KeyboardInterrupt]
    try:
        w._pump(sock)
    except KeyboardInterrupt:
        pass
    assert seen == [msg]
