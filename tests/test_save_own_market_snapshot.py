"""MainWindow._save_own_market_snapshot() -- persists the player's own
just-read Market.json straight into the local market_prices search table.
Previously this data only ever refreshed the live UI and (if EDDN
contribution happened to be enabled) got published outward -- the local
search index only ever got filled by EDDN's crowd feed relaying data
back, so a commander's own dock-and-buy never showed up in their own
market search until some other commander (or an EDDN round-trip of their
own publish) happened to report the same station. Confirmed live
2026-09-25. Fake self, same pattern as test_colonisation_depot_dedup.py."""
from types import SimpleNamespace

from edc.ui.main_window import MainWindow


def _fake_self():
    saved = []
    return SimpleNamespace(
        repo=SimpleNamespace(save_market_snapshot_batch=lambda records: saved.append(records)),
        _saved=saved,
    )


def _market(items, station_type="Orbis"):
    return {
        "timestamp": "2026-09-25T10:00:00Z",
        "event": "Market",
        "MarketID": 128049152,
        "StationName": "Jameson Memorial",
        "StationType": station_type,
        "StarSystem": "Shinrarta Dezhra",
        "Items": items,
    }


def _item(name="$platinum_name;", **overrides):
    it = {
        "id": 128049152,
        "Name": name,
        "Name_Localised": "Platinum",
        "Category": "$MARKET_category_metals;",
        "Category_Localised": "Metals",
        "BuyPrice": 0,
        "SellPrice": 59006,
        "MeanPrice": 55505,
        "StockBracket": 0,
        "DemandBracket": 3,
        "Stock": 0,
        "Demand": 33966,
        "Consumer": True,
        "Producer": False,
        "Rare": False,
    }
    it.update(overrides)
    return it


def test_valid_market_is_saved_with_station_type():
    fake_self = _fake_self()
    MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))
    assert fake_self._saved == [[(
        128049152, "platinum", "Jameson Memorial", "Orbis", "Shinrarta Dezhra",
        59006, 0, 55505, 33966, 3, 0, 0, "2026-09-25T10:00:00Z",
    )]]


def test_multiple_commodities_all_saved():
    fake_self = _fake_self()
    MainWindow._save_own_market_snapshot(
        fake_self, _market([_item(), _item(name="$aluminium_name;", SellPrice=100, MeanPrice=110)]),
    )
    assert len(fake_self._saved[0]) == 2
    names = {r[1] for r in fake_self._saved[0]}
    assert names == {"platinum", "aluminium"}


def test_missing_station_type_defaults_to_empty_string():
    fake_self = _fake_self()
    market = _market([_item()])
    del market["StationType"]
    MainWindow._save_own_market_snapshot(fake_self, market)
    assert fake_self._saved[0][0][3] == ""  # station_type field


def test_invalid_market_data_saves_nothing():
    fake_self = _fake_self()
    MainWindow._save_own_market_snapshot(fake_self, {"Items": []})  # missing required fields
    assert fake_self._saved == []


def test_repo_failure_is_caught_and_logged():
    saved_calls = []

    def _raise(records):
        saved_calls.append(records)
        raise RuntimeError("db error")

    fake_self = SimpleNamespace(repo=SimpleNamespace(save_market_snapshot_batch=_raise))
    MainWindow._save_own_market_snapshot(fake_self, _market([_item()]))  # must not raise
    assert len(saved_calls) == 1
