# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.
from edc.config import AppConfig, ConfigStore
from edc.core.exo_predictor import BodyPrediction, high_value_line


def P(up_to):
    return BodyPrediction({}, up_to)


def test_line_for_best_planet_only():
    out = high_value_line({"A 1": P(41_000_000), "B 2": P(35_000_000)}, 30)
    assert 'href="exobiology"' in out
    assert "🧬 High value exo planet: A 1, up to 41M" in out
    assert "B 2" not in out


def test_body_name_escaped():
    assert "A &lt;1&gt;" in high_value_line({"A <1>": P(41_000_000)}, 30)


def test_at_threshold_shows():
    assert "up to 30M" in high_value_line({"A 1": P(30_000_000)}, 30)


def test_below_threshold_empty():
    assert high_value_line({"A 1": P(29_999_999)}, 30) == ""


def test_finished_planet_clears():
    assert high_value_line({"A 1": P(0)}, 30) == ""
    assert high_value_line({}, 30) == ""


def test_config_default_and_roundtrip(tmp_path):
    assert AppConfig().exo_overview_alert_m == 30
    store = ConfigStore(tmp_path)
    cfg = store.load()
    assert cfg.exo_overview_alert_m == 30
    cfg.exo_overview_alert_m = 55
    store.save(cfg)
    assert ConfigStore(tmp_path).load().exo_overview_alert_m == 55


def test_exo_high_value_m_unchanged():
    assert AppConfig().exo_high_value_m == 2
