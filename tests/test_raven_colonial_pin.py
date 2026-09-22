"""RavenColonialPinStore -- persists the last-loaded Raven Colonial build
id to disk, same shape as MarketDestinationStore (its own tests are the
precedent this mirrors)."""
from edc.core.raven_colonial_pin import RavenColonialPinStore


def test_save_then_load_round_trips(tmp_path):
    store = RavenColonialPinStore(tmp_path / "pin.json")
    store.save("4e6a044c-e8a5-44e8-b93a-2484a7e2a894")
    assert store.load() == "4e6a044c-e8a5-44e8-b93a-2484a7e2a894"


def test_load_returns_none_when_no_file(tmp_path):
    store = RavenColonialPinStore(tmp_path / "pin.json")
    assert store.load() is None


def test_load_returns_none_for_malformed_json(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text("not valid json", encoding="utf-8")
    store = RavenColonialPinStore(path)
    assert store.load() is None


def test_load_returns_none_for_missing_build_id_field(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text('{"pinned_at": "2026-09-22T00:00:00Z"}', encoding="utf-8")
    store = RavenColonialPinStore(path)
    assert store.load() is None


def test_clear_removes_the_file(tmp_path):
    store = RavenColonialPinStore(tmp_path / "pin.json")
    store.save("abc-123")
    assert store.path.exists()
    store.clear()
    assert not store.path.exists()
    assert store.load() is None


def test_clear_is_a_noop_when_nothing_pinned(tmp_path):
    store = RavenColonialPinStore(tmp_path / "pin.json")
    store.clear()  # must not raise
    assert store.load() is None


def test_save_overwrites_a_previous_pin(tmp_path):
    store = RavenColonialPinStore(tmp_path / "pin.json")
    store.save("first-build-id")
    store.save("second-build-id")
    assert store.load() == "second-build-id"


def test_save_creates_parent_directory(tmp_path):
    store = RavenColonialPinStore(tmp_path / "nested" / "dir" / "pin.json")
    store.save("abc-123")
    assert store.load() == "abc-123"
