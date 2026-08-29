"""FdevPowerPlayCache parses Frontier's official PowerPlay CSV feed --
system/power names carry an internal id suffix in parens that must be
stripped, and lookups are name-keyed since the feed has no id64."""
from edc.core.fdev_powerplay import FdevPowerPlayCache

_SAMPLE_CSV = (
    '"10 Arietis (62982)","Pranav Antal (100090)","7","control","26","26","90","","30","4650","3365","14203","PASS",""\n'
    '"17 Cygni (74490)","Zachary Hudson (100060)","11","contested","","","","Venetic (2827959142763)","0","0","","","PASS",""\n'
)


def _cache(tmp_path, monkeypatch):
    cache = FdevPowerPlayCache(tmp_path)

    def _fake_get(url, headers, timeout):
        class _Resp:
            text = _SAMPLE_CSV
            def raise_for_status(self):
                pass
        return _Resp()

    import edc.core.fdev_powerplay as mod
    monkeypatch.setattr(mod.requests, "get", _fake_get)
    return cache


def test_refresh_strips_id_suffix_from_names(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    assert cache.refresh() is True

    rec = cache.get_by_name("10 Arietis")
    assert rec == {"power": "Pranav Antal", "state": "control", "value": 7}


def test_get_by_name_is_case_insensitive(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert cache.get_by_name("10 ARIETIS") == cache.get_by_name("10 arietis")


def test_contested_system_has_no_single_power_but_state_recorded(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    rec = cache.get_by_name("17 Cygni")
    assert rec["state"] == "contested"


def test_unknown_system_returns_none(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert cache.get_by_name("Sol") is None
