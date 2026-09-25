"""MainWindow._record_faction_combat_bond / _record_faction_cz_kill /
_record_faction_trade_sold -- feed the three new session-activity tables
from their respective journal events. Fake self, same pattern as
test_record_faction_mission_completion.py."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345, last_cz_credit=None, system_name="Ekono"):
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(system_address=system_address, last_cz_credit=last_cz_credit, system=system_name),
        repo=SimpleNamespace(
            save_system_name_if_missing=lambda *a, **kw: saved.append(("ensure_system", a)),
            record_faction_combat_bond=lambda **kw: saved.append(("bond", kw)),
            record_faction_cz_kill=lambda **kw: saved.append(("cz", kw)),
            record_faction_trade_sold=lambda **kw: saved.append(("trade", kw)),
        ),
        _saved=saved,
    )


# --- combat bonds ---

def test_combat_bond_is_recorded():
    fake_self = _fake_self()
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("bond", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "reward": 15000, "earned_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_combat_bond_skipped_without_awarding_faction():
    fake_self = _fake_self()
    evt = {"event": "FactionKillBond", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == []


def test_combat_bond_skipped_without_system_address():
    fake_self = _fake_self(system_address=None)
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_combat_bond(fake_self, evt)
    assert fake_self._saved == []


# --- CZ kills ---

def test_cz_kill_is_recorded_when_last_cz_credit_is_set():
    fake_self = _fake_self(last_cz_credit={"faction_name": "Elite United Worlds", "zone_type": "space", "size": "h"})
    evt = {"event": "FactionKillBond", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_cz_kill(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("cz", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "zone_type": "space", "size": "h", "earned_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_cz_kill_skipped_when_last_cz_credit_is_none():
    fake_self = _fake_self(last_cz_credit=None)
    evt = {"event": "FactionKillBond", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_cz_kill(fake_self, evt)
    assert fake_self._saved == []


# --- trade/exploration/exobiology sold ---

def test_market_sell_is_recorded_as_commodity():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("trade", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "kind": "commodity", "value": 63085, "sold_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_multi_sell_exploration_data_is_recorded_as_exploration():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "MultiSellExplorationData", "BaseValue": 1450787, "Bonus": 0,
           "TotalEarnings": 1305717, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("trade", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "kind": "exploration", "value": 1305717, "sold_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_legacy_sell_exploration_data_falls_back_to_base_plus_bonus():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {"event": "SellExplorationData", "BaseValue": 5000, "Bonus": 500, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("trade", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "kind": "exploration", "value": 5500, "sold_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_sell_organic_data_sums_biodata_as_exobiology():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = "Elite United Worlds"
    evt = {
        "event": "SellOrganicData", "timestamp": "2026-09-25T10:00:00Z",
        "BioData": [
            {"Species": "Fonticulua Digitos", "Value": 1804100, "Bonus": 0},
            {"Species": "Some Other Species", "Value": 200000, "Bonus": 50000},
        ],
    }
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("trade", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "kind": "exobiology", "value": 2054100, "sold_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_trade_sold_skipped_without_controlling_faction():
    fake_self = _fake_self()
    fake_self.state.controlling_faction = None
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == []


# --- bootstrap replay guard (dispatch level, in _on_event itself) ---
#
# The three _record_faction_* calls are gated by "and not self._replaying"
# on their dispatch conditions in _on_event -- the same style already used
# there for eddn_publisher.maybe_publish(...). A minimal MagicMock self
# lets _on_event run for real (exercising the actual dispatch conditions)
# while every collaborator it touches is an inert mock; only whether the
# three _record_* mocks got called is asserted.

def _dispatch_fake_self(replaying: bool):
    fake_self = MagicMock()
    fake_self._replaying = replaying
    fake_self.engine.process.return_value = (MagicMock(), [])
    fake_self.cfg.eddn_contribute_enabled = False
    return fake_self


def test_faction_kill_bond_dispatch_skipped_during_replay():
    fake_self = _dispatch_fake_self(replaying=True)
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_combat_bond.assert_not_called()
    fake_self._record_faction_cz_kill.assert_not_called()


def test_faction_kill_bond_dispatch_fires_when_not_replaying():
    fake_self = _dispatch_fake_self(replaying=False)
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_combat_bond.assert_called_once_with(evt)
    fake_self._record_faction_cz_kill.assert_called_once_with(evt)


def test_market_sell_dispatch_skipped_during_replay():
    fake_self = _dispatch_fake_self(replaying=True)
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_trade_sold.assert_not_called()


def test_market_sell_dispatch_fires_when_not_replaying():
    fake_self = _dispatch_fake_self(replaying=False)
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_trade_sold.assert_called_once_with(evt)
