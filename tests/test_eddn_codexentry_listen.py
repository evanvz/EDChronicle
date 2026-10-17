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
    msg = {"event": "CodexEntry", "Category": "$Codex_Category_Biology;",
           "SubCategory": "$Codex_SubCategory_Organic_Structures;", "SystemAddress": 42, "BodyID": 7,
           "EntryID": 2420201, "System": "X", "StarPos": [0, 0, 0], "timestamp": "2026-10-17T10:00:00Z"}
    vent = {**msg, "EntryID": 1400414, "SubCategory": "$Codex_SubCategory_Geology_and_Anomalies;"}  # same Category

    def raw(m):
        return zlib.compress(json.dumps({"$schemaRef": "https://eddn.edcd.io/schemas/codexentry/1",
                                         "header": {}, "message": m}).encode())
    sock = MagicMock()
    sock.recv.side_effect = [raw(vent), raw(msg), KeyboardInterrupt]
    try:
        w._pump(sock)
    except KeyboardInterrupt:
        pass
    assert seen == [msg]


def test_codexentry_name_from_canonn_list_before_own_log():
    import json
    from pathlib import Path
    names = json.loads((Path(__file__).resolve().parents[1] / "settings" / "codex_names.json").read_text(encoding="utf-8"))["names"]
    cache = EddnMarketCache(SimpleNamespace(get_codex_name=lambda eid: None), names)
    cache.on_codex_entry_seen({"event": "CodexEntry", "Category": "$Codex_Category_Biology;", "SystemAddress": 42,
                               "BodyID": 7, "EntryID": 2420201, "timestamp": "2026-10-17T10:00:00Z"})
    assert [r[2] for r in cache._codex_buffer.values()] == ["Stratum Paleas - Emerald"]
    assert len(names) == 816
