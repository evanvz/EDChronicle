"""EdAstroPoiCache -- EDAstro's community-curated POI catalog, cached
daily. get_nearest() computes distance locally rather than trusting
EDAstro's own remote "nearest" endpoint -- confirmed live 2026-09-24
that endpoint returns an unrelated result (Sol) regardless of input,
even when queried with a real POI's own exact coordinates."""
import json
from datetime import date

from edc.core.edastro_poi import EdAstroPoiCache


def _cache_with_pois(tmp_path, pois, fetched_date=None):
    path = tmp_path / "edastro_poi_cache.json"
    path.write_text(
        json.dumps({"fetched_date": fetched_date or date.today().isoformat(), "pois": pois}),
        encoding="utf-8",
    )
    return EdAstroPoiCache(tmp_path)


def _poi(name, x, y, z, rating=None, poi_type="Historical"):
    return {"name": name, "type": poi_type, "coordinates": [x, y, z], "rating": rating}


def test_get_nearest_returns_the_closest_poi(tmp_path):
    cache = _cache_with_pois(tmp_path, [
        _poi("Near", 1.0, 0.0, 0.0),
        _poi("Far", 100.0, 0.0, 0.0),
    ])
    nearest = cache.get_nearest(0.0, 0.0, 0.0)
    assert nearest["name"] == "Near"
    assert abs(nearest["distance_ly"] - 1.0) < 0.001


def test_get_nearest_returns_none_for_empty_cache(tmp_path):
    cache = EdAstroPoiCache(tmp_path)
    assert cache.get_nearest(0.0, 0.0, 0.0) is None


def test_get_nearest_skips_entries_without_valid_coordinates(tmp_path):
    cache = _cache_with_pois(tmp_path, [
        {"name": "Bad", "coordinates": None},
        _poi("Good", 5.0, 0.0, 0.0),
    ])
    nearest = cache.get_nearest(0.0, 0.0, 0.0)
    assert nearest["name"] == "Good"


def test_min_rating_filters_out_lower_rated_pois(tmp_path):
    cache = _cache_with_pois(tmp_path, [
        _poi("Nearby Low Rated", 1.0, 0.0, 0.0, rating=3.0),
        _poi("Farther High Rated", 50.0, 0.0, 0.0, rating=9.0),
    ])
    nearest = cache.get_nearest(0.0, 0.0, 0.0, min_rating=8.0)
    assert nearest["name"] == "Farther High Rated"


def test_min_rating_excludes_pois_with_no_rating_at_all(tmp_path):
    cache = _cache_with_pois(tmp_path, [_poi("Unrated", 1.0, 0.0, 0.0, rating=None)])
    assert cache.get_nearest(0.0, 0.0, 0.0, min_rating=1.0) is None


def test_is_stale_true_when_never_fetched(tmp_path):
    cache = EdAstroPoiCache(tmp_path)
    assert cache.is_stale() is True


def test_is_stale_false_for_todays_fetch(tmp_path):
    cache = _cache_with_pois(tmp_path, [_poi("X", 0, 0, 0)], fetched_date=date.today().isoformat())
    assert cache.is_stale() is False


def test_is_stale_true_for_yesterdays_fetch(tmp_path):
    cache = _cache_with_pois(tmp_path, [_poi("X", 0, 0, 0)], fetched_date="2020-01-01")
    assert cache.is_stale() is True


def test_has_data_and_poi_count(tmp_path):
    cache = _cache_with_pois(tmp_path, [_poi("A", 0, 0, 0), _poi("B", 1, 1, 1)])
    assert cache.has_data() is True
    assert cache.poi_count() == 2


def test_load_missing_file_returns_empty_not_an_error(tmp_path):
    cache = EdAstroPoiCache(tmp_path)
    assert cache.has_data() is False
    assert cache.poi_count() == 0


def test_load_malformed_json_returns_empty_not_an_error(tmp_path):
    path = tmp_path / "edastro_poi_cache.json"
    path.write_text("not valid json", encoding="utf-8")
    cache = EdAstroPoiCache(tmp_path)
    assert cache.has_data() is False
