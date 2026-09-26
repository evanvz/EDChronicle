"""MainWindow._record_faction_redeem_voucher / _record_faction_cz_kill /
_record_faction_trade_sold -- feed the session-activity tables from their
journal events. Fake self, same pattern as
test_record_faction_mission_completion.py.

BGS credit happens at cash-in, not at kill time: combat bonds and bounties
are recorded from RedeemVoucher, and only for factions present in the
current system (a voucher cashed in elsewhere has no effect there). Trade
and data sales credit the docked station's owner, never a fleet carrier.
Event shapes below are copied from real journal lines."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from edc.ui.main_window import MainWindow


def _fake_self(system_address=12345, last_cz_credit=None, system_name="Ekono",
               factions=("Elite United Worlds", "Hungarian Wolves"),
               station_faction="Elite United Worlds", station_type="Coriolis"):
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(
            system_address=system_address, last_cz_credit=last_cz_credit, system=system_name,
            factions=[{"Name": n} for n in factions],
            station_faction=station_faction, station_type=station_type,
        ),
        repo=SimpleNamespace(
            save_system_name_if_missing=lambda *a, **kw: saved.append(("ensure_system", a)),
            record_faction_combat_bond=lambda **kw: saved.append(("bond", kw)),
            record_faction_bounty=lambda **kw: saved.append(("bounty", kw)),
            record_faction_cz_kill=lambda **kw: saved.append(("cz", kw)),
            record_faction_trade_sold=lambda **kw: saved.append(("trade", kw)),
        ),
        _saved=saved,
    )


# --- combat bonds (RedeemVoucher Type CombatBond) ---

def test_combat_bond_cash_in_is_recorded():
    fake_self = _fake_self()
    evt = {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 181548,
           "Faction": "Elite United Worlds", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_redeem_voucher(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("bond", {
            "system_address": 12345, "faction_name": "Elite United Worlds",
            "reward": 181548, "earned_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_combat_bond_for_faction_not_in_system_is_skipped():
    # Real journal values: a power name, PilotsFederation, and blank at a broker.
    for faction in ("Aisling Duval", "PilotsFederation", ""):
        fake_self = _fake_self()
        evt = {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 136559,
               "Faction": faction, "BrokerPercentage": 25.0, "timestamp": "2026-09-25T10:00:00Z"}
        MainWindow._record_faction_redeem_voucher(fake_self, evt)
        assert fake_self._saved == [], faction


def test_voucher_skipped_without_system_address():
    fake_self = _fake_self(system_address=None)
    evt = {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 1000,
           "Faction": "Elite United Worlds", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_redeem_voucher(fake_self, evt)
    assert fake_self._saved == []


# --- bounties (RedeemVoucher Type bounty) ---

def test_bounty_cash_in_records_each_present_faction_and_skips_blank_and_absent():
    fake_self = _fake_self()
    evt = {"event": "RedeemVoucher", "Type": "bounty", "Amount": 710148, "timestamp": "2026-09-25T10:00:00Z",
           "Factions": [
               {"Faction": "", "Amount": 528718},
               {"Faction": "Hungarian Wolves", "Amount": 150000},
               {"Faction": "Prismatic Imperium", "Amount": 31430},
           ]}
    MainWindow._record_faction_redeem_voucher(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("bounty", {
            "system_address": 12345, "faction_name": "Hungarian Wolves",
            "amount": 150000, "redeemed_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_other_voucher_types_are_ignored():
    for vtype in ("trade", "codex", "settlement", "scannable"):
        fake_self = _fake_self()
        evt = {"event": "RedeemVoucher", "Type": vtype, "Amount": 12900, "timestamp": "2026-09-25T10:00:00Z"}
        MainWindow._record_faction_redeem_voucher(fake_self, evt)
        assert fake_self._saved == [], vtype


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

def test_market_sell_is_recorded_as_commodity_profit_for_station_faction():
    fake_self = _fake_self(station_faction="Hungarian Wolves")
    evt = {"event": "MarketSell", "Count": 150, "SellPrice": 9000, "TotalSale": 1350000,
           "AvgPricePaid": 5000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == [
        ("ensure_system", (12345, "Ekono")),
        ("trade", {
            "system_address": 12345, "faction_name": "Hungarian Wolves",
            "kind": "commodity", "value": 600000, "sold_at": "2026-09-25T10:00:00Z",
        }),
    ]


def test_market_sell_without_avg_price_paid_counts_full_sale():
    fake_self = _fake_self()
    evt = {"event": "MarketSell", "Count": 10, "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved[-1][1]["value"] == 63085


def test_multi_sell_exploration_data_is_recorded_as_exploration():
    fake_self = _fake_self()
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
    evt = {"event": "SellExplorationData", "BaseValue": 5000, "Bonus": 500, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved[-1] == ("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "exploration", "value": 5500, "sold_at": "2026-09-25T10:00:00Z",
    })


def test_sell_organic_data_sums_biodata_as_exobiology():
    fake_self = _fake_self()
    evt = {
        "event": "SellOrganicData", "timestamp": "2026-09-25T10:00:00Z",
        "BioData": [
            {"Species": "Fonticulua Digitos", "Value": 1804100, "Bonus": 0},
            {"Species": "Some Other Species", "Value": 200000, "Bonus": 50000},
        ],
    }
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved[-1] == ("trade", {
        "system_address": 12345, "faction_name": "Elite United Worlds",
        "kind": "exobiology", "value": 2054100, "sold_at": "2026-09-25T10:00:00Z",
    })


def test_trade_sold_skipped_without_station_faction():
    fake_self = _fake_self(station_faction=None)
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == []


def test_trade_sold_skipped_at_fleet_carrier():
    fake_self = _fake_self(station_faction="FleetCarrier", station_type="FleetCarrier")
    evt = {"event": "MarketSell", "TotalSale": 63085, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._record_faction_trade_sold(fake_self, evt)
    assert fake_self._saved == []


# --- bootstrap replay guard (dispatch level, in _on_event itself) ---
#
# The _record_faction_* calls are gated by "and not self._replaying" on
# their dispatch conditions in _on_event. A minimal MagicMock self lets
# _on_event run for real while every collaborator is an inert mock.

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
    fake_self._record_faction_cz_kill.assert_not_called()


def test_faction_kill_bond_dispatch_records_cz_kill_only():
    fake_self = _dispatch_fake_self(replaying=False)
    evt = {"event": "FactionKillBond", "AwardingFaction": "Elite United Worlds", "Reward": 15000, "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_cz_kill.assert_called_once_with(evt)
    fake_self._record_faction_redeem_voucher.assert_not_called()


def test_redeem_voucher_dispatch_skipped_during_replay():
    fake_self = _dispatch_fake_self(replaying=True)
    evt = {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 1000, "Faction": "X", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_redeem_voucher.assert_not_called()


def test_redeem_voucher_dispatch_fires_when_not_replaying():
    fake_self = _dispatch_fake_self(replaying=False)
    evt = {"event": "RedeemVoucher", "Type": "CombatBond", "Amount": 1000, "Faction": "X", "timestamp": "2026-09-25T10:00:00Z"}
    MainWindow._on_event(fake_self, evt)
    fake_self._record_faction_redeem_voucher.assert_called_once_with(evt)


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
