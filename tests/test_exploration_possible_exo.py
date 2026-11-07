# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import sys
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QLabel

from edc.core.exo_predictor import BodyPrediction
from edc.ui.panels.exploration_panel import ExplorationPanel

_app = QApplication.instance() or QApplication(sys.argv)

CFG = SimpleNamespace(min_planet_value_100k=5)


def _state():
    return SimpleNamespace(
        bodies={
            "Sys 1": {"BodyID": 1, "EstimatedValue": 100, "BioSignals": 1},
            "Sys 2": {"BodyID": 2, "EstimatedValue": 900, "BioSignals": 1},
        },
        system_body_count=2, resolved_body_ids=set(), rings={}, system_signals=[],
        system_address=1, fss_complete=False,
    )


def _pred(names, up_to):
    return BodyPrediction({n: [] for n in names}, up_to)


def _texts(panel, body):
    return [l for l in panel._body_cards[body][0].findChildren(QLabel)]


def _refresh(panel, preds):
    panel.refresh(_state(), CFG, None, exo_predictions=preds)


def test_card_shows_possible_line():
    p = ExplorationPanel()
    _refresh(p, {"Sys 1": _pred(["Bacterium", "Fungoida"], 20_000_000)})
    lbl = next(l for l in _texts(p, "Sys 1") if "Possible:" in l.text())
    assert "Bacterium, Fungoida" in lbl.text() and "up to 20.0M" in lbl.text()
    assert "#888888" in lbl.styleSheet()


def test_card_updates_when_prediction_changes():
    p = ExplorationPanel()
    _refresh(p, {"Sys 1": _pred(["Bacterium"], 1_000_000)})
    _refresh(p, {"Sys 1": _pred(["Fungoida"], 2_000_000)})
    txt = " ".join(l.text() for l in _texts(p, "Sys 1"))
    assert "Fungoida" in txt and "Bacterium" not in txt


def test_no_prediction_no_line():
    p = ExplorationPanel()
    _refresh(p, None)
    assert not any("Possible:" in l.text() for l in _texts(p, "Sys 1"))


def test_sort_order_unchanged():
    p = ExplorationPanel()
    _refresh(p, {"Sys 1": _pred(["Bacterium"], 99_000_000)})
    lay = p._cards_layout
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert order.index(p._body_cards["Sys 2"][0]) < order.index(p._body_cards["Sys 1"][0])


def test_card_shows_sighted_species_with_no_possible():
    p = ExplorationPanel()
    _refresh(p, {"Sys 1": BodyPrediction({}, 8_000_000, known={"X": ("X Two", 8_000_000)})})
    lbl = next(l for l in _texts(p, "Sys 1") if "Sighted:" in l.text())
    assert lbl.text() == "Sighted: X Two · up to 8.0M" and "#888888" in lbl.styleSheet()


def test_card_after_dss_says_possible_species():
    p = ExplorationPanel()
    _refresh(p, {"Sys 1": BodyPrediction({"X": [("X One", 8_000_000), ("X Two", 1)]}, 8_000_000, after_dss=True)})
    txt = " ".join(l.text() for l in _texts(p, "Sys 1"))
    assert "Possible species: X One, X Two · up to 8.0M" in txt and "Possible: " not in txt
