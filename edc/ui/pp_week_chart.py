# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
"""Small step chart of a system's PowerPlay undermining (U) and reinforcement
(R) since the weekly reset, for the PowerPlay Status tab."""
from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from edc.core.bgs_tasks import _hours_ago
from edc.core.pp_week import _t

_U, _R, _AXIS = "#FF6B6B", "#4D96FF", "#777777"


class PPWeekChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._readings = []
        self._week_start = None
        self._now = None

    def sizeHint(self) -> QSize:
        return QSize(400, 90)

    def set_data(self, readings: list, week_start: str, now: datetime) -> None:
        self._readings, self._week_start, self._now = readings, week_start, now
        self.update()

    def caption(self) -> str:
        if not self._readings:
            return ""
        return f"{len(self._readings)} reports this week · last {_hours_ago(self._readings[-1]['observed_at'])}"

    def paintEvent(self, event) -> None:
        if not self._readings:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = 4, 4, self.width() - 70, self.height() - 16
        start, now = _t(self._week_start), self._now
        span = max((now - start).total_seconds(), 1)
        top_v = max([1] + [r[k] for r in self._readings for k in ("undermining", "reinforcement")
                           if r[k] is not None])

        def x(t):
            return left + (right - left) * min(max((t - start).total_seconds() / span, 0), 1)

        def y(v):
            return bottom - (bottom - top) * v / top_v

        p.setPen(QColor(_AXIS))
        p.drawLine(left, bottom, right, bottom)
        day = start
        while day <= now:
            p.drawText(int(x(day)) + 2, self.height() - 3, day.astimezone().strftime("%a"))
            day += timedelta(days=1)

        latest = []
        for key, colour in (("undermining", _U), ("reinforcement", _R)):
            pts = [(_t(r["observed_at"]), r[key]) for r in self._readings if r[key] is not None]
            if not pts:
                continue
            p.setPen(QPen(QColor(colour), 2))
            for (t, v), (t2, v2) in zip(pts, pts[1:] + [(now, None)]):
                p.drawLine(QPointF(x(t), y(v)), QPointF(x(t2), y(v)))
                if v2 is not None:
                    p.drawLine(QPointF(x(t2), y(v)), QPointF(x(t2), y(v2)))
            latest.append((key[0].upper(), pts[-1][1], colour))
        for i, (name, v, colour) in enumerate(latest):
            p.setPen(QColor(colour))
            p.drawText(right + 6, top + 14 + i * 16, f"{name} {v:,}")
        p.end()
