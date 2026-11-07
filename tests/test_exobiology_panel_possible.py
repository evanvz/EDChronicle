# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import sys
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from edc.core.exo_predictor import BodyPrediction
from edc.ui.panels.exobiology_panel import ExobiologyPanel, _row_sort_key

_app = QApplication.instance() or QApplication(sys.argv)

VALUES = SimpleNamespace(by_species={
    "Bacterium Aurasus": SimpleNamespace(base_value=1_000_000, genus="Bacterium"),
    "Fonticulua Segmentatus": SimpleNamespace(base_value=19_000_000, genus="Fonticulua"),
    "Brain Tree Roseum": SimpleNamespace(base_value=3_000_000, genus="Brain Tree"),
})


def _state(bodies, exo=None):
    return SimpleNamespace(
        bodies=bodies, exo=exo or {}, bio_signals={}, bio_genuses={}, geo_signals={},
        body_id_to_name={}, system="Sys",
    )


def _text(state, preds, canonn_poi=None):
    p = ExobiologyPanel()
    p.refresh(state, SimpleNamespace(exo_high_value_m=2), VALUES, canonn_poi=canonn_poi, exo_predictions=preds)
    return p.exo_display.toPlainText()


def _pred(possible, up_to):
    return BodyPrediction(possible, up_to)


def test_needs_dss_row_shows_possible_and_up_to():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 2}})
    preds = {"Sys 1": _pred({"Bacterium": [("Bacterium Aurasus", 1_000_000)],
                             "Fonticulua": [("Fonticulua Segmentatus", 19_000_000)]}, 20_000_000)}
    t = _text(st, preds)
    assert "NEEDS DSS" in t and "possible: Bacterium, Fonticulua" in t and "up to 20.0M" in t


def test_canonn_hint_keeps_priority():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1}})
    poi = SimpleNamespace(codex=[SimpleNamespace(body="1", name="Bacterium Aurasus")])
    preds = {"Sys 1": _pred({"Bacterium": [("Bacterium Aurasus", 1_000_000)]}, 1_000_000)}
    t = _text(st, preds, poi)
    assert "Canonn: Bacterium Aurasus" in t and "possible:" not in t


def test_after_dss_lists_possible_species_and_fit_limited_top():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Brain Trees"]}})
    preds = {"Sys 1": _pred({"Brain Tree": [("Brain Tree Roseum", 3_000_000)]}, 3_000_000)}
    t = _text(st, preds)
    assert "UNSCANNED" in t and "possible: Brain Tree Roseum" in t and "up to 3,000,000 cr" in t


def test_after_dss_empty_prediction_falls_back():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}})
    t = _text(st, {"Sys 1": _pred({}, 0)})
    assert "possible:" not in t and "Bacterium" in t


def test_no_predictions_renders_as_today():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}})
    t = _text(st, None)
    assert t.splitlines()[1].split() == ["UNSCANNED", "Bacterium", "0/3"]


def test_rank_by_up_to_across_needs_dss_and_unscanned():
    up = {"A": 5_000_000, "B": 40_000_000}
    a = (0, "NEEDS DSS (Bio: 1)", "A", "g", "", "", "", "", "0/3", "x")
    b = (0, "UNSCANNED", "B", "g", "", "", "", "", "0/3", "x")
    c = (3, "COMPLETE", "C", "g", "", "", "", "", "3/3", "x")
    assert [r[2] for r in sorted([c, a, b], key=lambda r: _row_sort_key(r, up))] == ["B", "A", "C"]


def test_codex_hint_keeps_genus_max_not_fit_top():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}},
                {"k": {"BodyID": 1, "Genus": "Bacterium", "Species": "Bacterium Aurasus", "LastScanType": "CODEX"}})
    preds = {"Sys 1": _pred({"Bacterium": [("Bacterium Aurasus", 1)]}, 1)}
    p = ExobiologyPanel()
    p.refresh(st, SimpleNamespace(exo_high_value_m=1), VALUES, exo_predictions=preds)
    assert "possible:" not in p.exo_display.toPlainText()
    assert "1 high-value" in p.exo_action.text()


def test_exo_predictions_swallows_errors(monkeypatch):
    from edc.ui import main_window as mw
    monkeypatch.setattr(mw, "predict_system", lambda *a: 1 / 0)
    me = SimpleNamespace(state=None, exo_rules=[], exo_values=None, _codex_sightings=lambda: {})
    assert mw.MainWindow._exo_predictions(me) == {}


SIGHTED = {"Bacterium": ("Bacterium Aurasus", 1_000_000)}


def test_needs_dss_row_names_sighted_species_and_value():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 2}})
    preds = {"Sys 1": BodyPrediction({"Fonticulua": [("Fonticulua Segmentatus", 19_000_000)]}, 20_000_000, known=SIGHTED)}
    t = _text(st, preds)
    assert "sighted: Bacterium Aurasus 1,000,000 cr" in t and "possible: Fonticulua" in t and "up to 20.0M" in t


def test_after_dss_row_names_sighted_species_and_value():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}})
    t = _text(st, {"Sys 1": BodyPrediction({}, 1_000_000, known=SIGHTED)})
    assert "UNSCANNED" in t and "sighted: Bacterium Aurasus" in t and "1,000,000 cr" in t and "possible:" not in t


def test_sighted_after_dss_is_dim_not_gold():
    st = _state({"Sys 1": {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}})
    p = ExobiologyPanel()
    p.refresh(st, SimpleNamespace(exo_high_value_m=2), VALUES,
              exo_predictions={"Sys 1": BodyPrediction({}, 1_000_000, known=SIGHTED)})
    h = p.exo_display.toHtml().lower()
    assert "#ffd93d" not in h and "#888888" in h


def _sampled_state(bodyrec):
    return _state({"Sys 1": bodyrec},
                  {"k": {"BodyID": 1, "Genus": "Bacterium", "Species": "Bacterium Aurasus", "Samples": 1,
                         "LastScanType": "LOG", "BaseValue": 1_000_000}})


def test_sampled_row_is_not_duplicated_or_labelled_sighted():
    preds = {"Sys 1": BodyPrediction({}, 1_000_000, known=SIGHTED, sampled=frozenset({"Bacterium"}))}
    for rec in ({"BodyID": 1, "BioSignals": 2}, {"BodyID": 1, "BioSignals": 1, "BioGenuses": ["Bacterium"]}):
        t = _text(_sampled_state(rec), preds)
        assert "sighted:" not in t and t.count("Bacterium Aurasus") == 1
