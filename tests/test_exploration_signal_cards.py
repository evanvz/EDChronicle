"""System signals shown as one card per category on a fixed grid (Evan's design 2026-11-12):
every card always present, so the layout doesn't jump between systems."""
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from edc.ui.panels.exploration_panel import SIGNAL_CARDS, ExplorationPanel, signal_card  # noqa: E402


def _sig(name, signal_type, category="Other", **kw):
    return {"SignalName": name, "SignalType": signal_type, "Category": category, **kw}


# Sorbago, 2026-11-11: everything but the stations and installations used to land in "Other"
SORBAGO = [
    _sig("Coldwood", "StationCoriolis", "Station"),
    _sig("Hencke Orbital", "StationONeilOrbis", "Station"),
    _sig("Berners Park", "Installation", "Installation"),
    _sig("Carroll Survey", "Outpost"),
    _sig("Conflict Zone [Low Intensity]", "Combat"),
    _sig("Nav Beacon", "NavBeacon", "NavBeacon"),
    _sig("Capital Ship", "Generic"),
    _sig("Sorbago Slave Rebellion", "TouristBeacon", "TouristBeacon"),
    _sig("Some Carrier XYZ-123", "FleetCarrier", "FleetCarrier"),
]


def test_signals_sort_into_their_own_cards():
    assert [signal_card(s) for s in SORBAGO] == [
        "STATIONS", "STATIONS", "INSTALLATIONS", "OUTPOSTS", "COMBAT SITES", "BEACONS",
        "CAPITAL SHIPS & MEGASHIPS", "BEACONS", None]
    assert signal_card(_sig("Stronghold Carrier", "StationMegaShip", "Station")) == "CAPITAL SHIPS & MEGASHIPS"
    assert signal_card(_sig("Resource Extraction Site [High]", "ResourceExtraction", "RES")) == "COMBAT SITES"
    assert signal_card(_sig("Pirate Activity Detected [Threat 6]", "Generic")) == "COMBAT SITES"
    assert signal_card(_sig("Debris field", "Generic")) == "USS / WRECKAGE"
    assert signal_card(_sig("Squadron Carrier", "SquadronCarrier", "Station")) is None
    assert signal_card(_sig("Checkpoint", "Generic")) == "PHENOMENA / OTHER"


def test_every_card_always_shown_with_counts():
    p = ExplorationPanel()
    p._refresh_signals(SimpleNamespace(system_signals=SORBAGO))
    titles = {t: lbl.text() for t, (lbl, _) in p._sig_cards.items()}
    assert list(titles) == list(SIGNAL_CARDS)
    assert titles["STATIONS"] == "STATIONS  2" and titles["BEACONS"] == "BEACONS  2"
    assert titles["USS / WRECKAGE"] == "USS / WRECKAGE"
    assert "—" in p._sig_cards["USS / WRECKAGE"][1].text()
    assert "Carroll Survey" in p._sig_cards["OUTPOSTS"][1].text()
    assert "8 signals" in p.system_signals_box.text()
    p._toggle_signals()
    assert p._sig_grid.isHidden()
