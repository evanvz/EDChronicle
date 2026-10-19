# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Faction influence-over-time line chart, drawn with QPainter.

Replaces QtCharts: Windows Smart App Control blocked PyQt6's QtCharts.pyd
(unsigned, low reputation) on 2026-10-19, while QtGui/QtWidgets -- which this
uses -- load fine. One line per faction, dates along the bottom, influence %
up the side, a legend across the top.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

Series = Tuple[str, str, List[Tuple[date, float]]]   # (faction, colour, [(day, influence %)])

_BG = QColor("#080f18")
_GRID = QColor("#1e3a5a")
_LABEL = QColor("#888888")
_TEXT = QColor("#c8c8c8")


class InfluenceChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._series: List[Series] = []
        self._lo, self._hi = 0.0, 100.0
        self.setMinimumHeight(220)

    def set_data(self, series: List[Series], y_range: Tuple[float, float] = (0.0, 100.0)) -> None:
        self._series = [s for s in series if s[2]]
        self._lo, self._hi = y_range
        self.update()

    def _x_span(self) -> Optional[Tuple[int, int]]:
        days = [d.toordinal() for _, _, pts in self._series for d, _ in pts]
        return (min(days), max(days)) if days else None

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)
        fm = QFontMetrics(self.font())
        p.setFont(self.font())

        # legend: one row (wrapping) across the top
        x, y, row_h = 8.0, 6.0, fm.height() + 2
        for name, colour, _ in self._series:
            w = 14 + fm.horizontalAdvance(name) + 12
            if x + w > self.width() - 8 and x > 8:
                x, y = 8.0, y + row_h
            p.setPen(QPen(QColor(colour), 3))
            p.drawLine(QPointF(x, y + row_h / 2), QPointF(x + 10, y + row_h / 2))
            p.setPen(_TEXT)
            p.drawText(QPointF(x + 14, y + fm.ascent()), name)
            x += w
        top = y + row_h + 6 if self._series else 8.0

        left = fm.horizontalAdvance("100%") + 12
        plot = QRectF(left, top, max(10.0, self.width() - left - 16), max(10.0, self.height() - top - fm.height() - 12))
        span = self._x_span()
        lo, hi = self._lo, (self._hi if self._hi > self._lo else self._lo + 1)

        def to_y(v: float) -> float:
            return plot.bottom() - (v - lo) / (hi - lo) * plot.height()

        # horizontal grid + % labels
        for i in range(6):
            v = lo + (hi - lo) * i / 5
            gy = to_y(v)
            p.setPen(QPen(_GRID, 1))
            p.drawLine(QPointF(plot.left(), gy), QPointF(plot.right(), gy))
            p.setPen(_LABEL)
            label = f"{v:.0f}%"
            p.drawText(QPointF(plot.left() - 6 - fm.horizontalAdvance(label), gy + fm.ascent() / 2 - 1), label)

        if not span:
            p.setPen(_LABEL)
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No influence history yet")
            p.end()
            return
        d0, d1 = span
        width_days = max(1, d1 - d0)

        def to_x(d: date) -> float:
            return plot.left() + (d.toordinal() - d0) / width_days * plot.width()

        # date labels: about one per 90 px
        steps = max(1, min(width_days, int(plot.width() // 90)))
        p.setPen(_LABEL)
        for i in range(steps + 1):
            d = date.fromordinal(d0 + round(width_days * i / steps))
            label = d.strftime("%b %d").replace(" 0", " ")
            lx = to_x(d) - fm.horizontalAdvance(label) / 2
            lx = min(max(lx, plot.left()), plot.right() - fm.horizontalAdvance(label))
            p.drawText(QPointF(lx, plot.bottom() + fm.ascent() + 4), label)

        # one line per faction, with dots on each reading
        for _, colour, pts in self._series:
            pen = QPen(QColor(colour), 2)
            p.setPen(pen)
            line = [QPointF(to_x(d), to_y(v)) for d, v in sorted(pts)]
            for a, b in zip(line, line[1:]):
                p.drawLine(a, b)
            p.setBrush(QColor(colour))
            for pt in line:
                p.drawEllipse(pt, 2.5, 2.5)
        p.end()
