"""GuardianRuinsCache parses Canonn's get_gr_data response -- confirmed
live: a flat JSON array of {"system": ..., "x": ..., "y": ..., "z": ...}."""
from edc.core.guardian_ruins import GuardianRuinsCache

_SAMPLE_RESPONSE = [
    {"system": "Blaa Hypai BN-I b26-1", "x": "1290.31250", "y": "-666.37500", "z": "12299.59375"},
    {"system": "Synuefe NL-N c23-4", "x": "0", "y": "0", "z": "0"},
]


def _cache(tmp_path, monkeypatch, payload=_SAMPLE_RESPONSE, status_code=200):
    cache = GuardianRuinsCache(tmp_path)

    class _Resp:
        def json(self):
            return payload
        def raise_for_status(self):
            if status_code >= 400:
                raise Exception(f"HTTP {status_code}")

    def _fake_get(url, headers, timeout):
        return _Resp()

    import edc.core.guardian_ruins as mod
    monkeypatch.setattr(mod.requests, "get", _fake_get)
    return cache


def test_refresh_populates_known_systems(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    assert cache.refresh() is True
    assert cache.has_ruins("Synuefe NL-N c23-4") is True
    assert cache.has_ruins("synuefe nl-n c23-4") is True  # case-insensitive


def test_has_ruins_false_for_unknown_system(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()
    assert cache.has_ruins("Sol") is False


def test_has_ruins_false_before_any_refresh(tmp_path, monkeypatch):
    cache = GuardianRuinsCache(tmp_path)
    assert cache.has_ruins("Synuefe NL-N c23-4") is False


def test_has_ruins_handles_none_and_blank(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()
    assert cache.has_ruins(None) is False
    assert cache.has_ruins("") is False


def test_refresh_fails_on_unexpected_shape(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch, payload={"not": "a list"})
    assert cache.refresh() is False
    assert cache.has_data() is False


def test_refresh_fails_on_empty_list(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch, payload=[])
    assert cache.refresh() is False


def test_is_stale_true_before_first_refresh(tmp_path, monkeypatch):
    cache = GuardianRuinsCache(tmp_path)
    assert cache.is_stale() is True


def test_is_stale_false_immediately_after_refresh(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()
    assert cache.is_stale() is False


def test_persists_and_reloads_from_disk(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    reloaded = GuardianRuinsCache(tmp_path)
    assert reloaded.has_ruins("Synuefe NL-N c23-4") is True
    assert reloaded.is_stale() is False
