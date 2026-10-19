"""QPainter influence chart (replaces QtCharts, which Windows Smart App
Control blocked on 2026-10-19)."""
from datetime import date

from PyQt6.QtWidgets import QApplication

from edc.ui.influence_chart import InfluenceChart


def test_draws_lines_and_empty_state():
    app = QApplication.instance() or QApplication([])
    ch = InfluenceChart()
    ch.resize(600, 260)
    assert not ch.grab().isNull()                                      # empty: "No influence history yet"
    ch.set_data([("EUW", "#FF6B6B", [(date(2026, 10, 1), 80.0), (date(2026, 10, 2), 70.0)]),
                 ("Nobody", "#4da3ff", [])], (60.0, 90.0))
    assert [s[0] for s in ch._series] == ["EUW"]                       # empty series dropped
    assert ch._x_span() == (date(2026, 10, 1).toordinal(), date(2026, 10, 2).toordinal())
    img = ch.grab().toImage()
    assert not img.isNull() and img.width() > 0
