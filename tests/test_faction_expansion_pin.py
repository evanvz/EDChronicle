"""FactionExpansionPinStore -- persists the target system tracked on the
Faction Expansion window, same shape as RavenColonialPinStore/
MarketDestinationStore (their own tests are the precedent this mirrors)."""
from edc.core.faction_expansion_pin import FactionExpansionPinStore


def test_save_then_load_round_trips(tmp_path):
    store = FactionExpansionPinStore(tmp_path / "pin.json")
    store.save("Ekono")
    assert store.load() == "Ekono"


def test_load_returns_none_when_no_file(tmp_path):
    store = FactionExpansionPinStore(tmp_path / "pin.json")
    assert store.load() is None


def test_load_returns_none_for_malformed_json(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text("not valid json", encoding="utf-8")
    store = FactionExpansionPinStore(path)
    assert store.load() is None


def test_load_returns_none_for_missing_system_name_field(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text('{"pinned_at": "2026-09-24T00:00:00Z"}', encoding="utf-8")
    store = FactionExpansionPinStore(path)
    assert store.load() is None


def test_clear_removes_the_file(tmp_path):
    store = FactionExpansionPinStore(tmp_path / "pin.json")
    store.save("Ekono")
    assert store.path.exists()
    store.clear()
    assert not store.path.exists()
    assert store.load() is None


def test_clear_is_a_noop_when_nothing_pinned(tmp_path):
    store = FactionExpansionPinStore(tmp_path / "pin.json")
    store.clear()  # must not raise
    assert store.load() is None


def test_save_overwrites_a_previous_pin(tmp_path):
    store = FactionExpansionPinStore(tmp_path / "pin.json")
    store.save("Ekono")
    store.save("HIP 105879")
    assert store.load() == "HIP 105879"
