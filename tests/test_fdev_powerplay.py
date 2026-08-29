"""FdevPowerPlayCache parses Frontier's official PowerPlay CSV feeds --
system/power names carry an internal id suffix in parens that must be
stripped, and lookups are name-keyed since neither feed has an id64."""
from edc.core.fdev_powerplay import FdevPowerPlayCache, _FEED_URL, _PREP_URL

_SAMPLE_CONTROL_CSV = (
    '"10 Arietis (62982)","Pranav Antal (100090)","7","control","26","26","90","","30","4650","3365","14203","PASS",""\n'
    '"17 Cygni (74490)","Zachary Hudson (100060)","11","contested","","","","Venetic (2827959142763)","0","0","","","PASS",""\n'
)

_SAMPLE_PREP_CSV = (
    '"A. Lavigny-Duval (100020)","HIP 10123 (5619)","50045","40802","24079","10","",""\n'
    '"A. Lavigny-Duval (100020)","HIP 10716 (5945)","50038","40759","24044","264","",""\n'
)


def _cache(tmp_path, monkeypatch):
    cache = FdevPowerPlayCache(tmp_path)

    def _fake_get(url, headers, timeout):
        class _Resp:
            text = _SAMPLE_PREP_CSV if url == _PREP_URL else _SAMPLE_CONTROL_CSV
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
    assert rec == {
        "system": "10 Arietis", "power": "Pranav Antal", "state": "control", "value": 7,
        "qty_for": 30, "qty_against": 4650, "thr_for": 3365, "thr_against": 14203,
        "prediction": "PASS",
    }


def test_contested_row_with_blank_thresholds_parses_as_none(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    rec = cache.get_by_name("17 Cygni")
    assert rec["qty_for"] == 0
    assert rec["qty_against"] == 0
    assert rec["thr_for"] is None
    assert rec["thr_against"] is None
    assert rec["prediction"] == "PASS"


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


def test_get_systems_for_power_filters_by_power(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    rows = cache.get_systems_for_power("Pranav Antal")
    assert len(rows) == 1
    assert rows[0]["system"] == "10 Arietis"


def test_get_systems_for_power_is_case_insensitive(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert len(cache.get_systems_for_power("pranav antal")) == 1


def test_get_systems_for_power_unknown_power_returns_empty(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert cache.get_systems_for_power("Nobody") == []


def test_preparation_feed_parses_coords_and_strips_id_suffix(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    rows = cache.get_preparation_systems("A. Lavigny-Duval")
    assert len(rows) == 2
    assert rows[0] == {"system": "HIP 10123", "x": 50045.0, "y": 40802.0, "z": 24079.0, "value": 10}


def test_preparation_lookup_is_case_insensitive(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert cache.get_preparation_systems("a. lavigny-duval") == cache.get_preparation_systems("A. Lavigny-Duval")


def test_preparation_lookup_unknown_power_returns_empty(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    assert cache.get_preparation_systems("Nobody") == []


def test_refresh_persists_and_reloads_preparation_data(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    cache.refresh()

    reloaded = FdevPowerPlayCache(tmp_path)
    rows = reloaded.get_preparation_systems("A. Lavigny-Duval")
    assert len(rows) == 2
