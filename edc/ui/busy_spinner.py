"""Shared floating 'busy' indicator — used by any panel with a background
search worker (Market, Mining, PowerPlay Target Finder, ...). Factored out
once a third panel needed the identical widget, rather than duplicating it.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QPoint, QPointF, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


class BusySpinner(QWidget):
    """
    Floating 'busy' indicator — a ring of dots, rotating, each sized and
    colored by its position behind the leading dot (biggest + brightest
    orange at the head, shrinking and paling toward the tail) — drawn with
    QPainter, no image/GIF assets needed. Not placed in any layout; floats
    via manual positioning over whatever widget it's given, as a sibling
    (same parent) so their geometries share one coordinate space.
    Repositions on start_over(); doesn't track the parent resizing mid-spin
    (a live search is brief enough that this is a non-issue in practice).
    """
    _N_DOTS = 12
    _SIZE = 72
    _MIN_DOT_R = 1.0
    _MAX_DOT_R = 7.0
    _COLOR_LIGHT = QColor(255, 224, 178)  # pale orange — tail
    _COLOR_BRIGHT = QColor(255, 140, 0)   # bright orange — head

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._leading = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self._SIZE, self._SIZE)
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self) -> None:
        self._leading = (self._leading + 1) % self._N_DOTS
        self.update()

    @staticmethod
    def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
        return QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * t),
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        center = self._SIZE / 2.0
        orbit_r = center - self._MAX_DOT_R - 2.0
        for i in range(self._N_DOTS):
            # 0 at the leading (head) dot, growing toward the tail.
            behind = (self._leading - i) % self._N_DOTS
            t = 1.0 - behind / self._N_DOTS
            radius = self._MIN_DOT_R + (self._MAX_DOT_R - self._MIN_DOT_R) * t
            painter.setBrush(self._lerp_color(self._COLOR_LIGHT, self._COLOR_BRIGHT, t))
            angle = 2 * math.pi * i / self._N_DOTS - math.pi / 2
            x = center + orbit_r * math.cos(angle)
            y = center + orbit_r * math.sin(angle)
            painter.drawEllipse(QPointF(x, y), radius, radius)

    def start_over(self, target: QWidget) -> None:
        """Shows the spinner centered over `target`'s visible area — pass
        the panel itself (this spinner's own parent) to center on the
        whole visible area rather than tucked over one card. `target` can
        also be a sibling widget (sharing this spinner's parent); either
        way its top-left is mapped into this spinner's parent coordinate
        space before centering, since .geometry() is parent-relative but
        target-IS-the-parent needs its own (0,0)-based .rect() instead."""
        parent = self.parentWidget()
        if target is parent or parent is None:
            top_left = QPoint(0, 0)
        else:
            top_left = target.mapTo(parent, QPoint(0, 0))
        cx = top_left.x() + target.width() // 2
        cy = top_left.y() + target.height() // 2
        self.move(cx - self._SIZE // 2, cy - self._SIZE // 2)
        self._leading = 0
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()
