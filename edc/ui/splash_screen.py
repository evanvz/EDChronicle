import math
import random
import threading
import logging

log = logging.getLogger(__name__)

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QPolygonF, QBrush

ASCII_HEADER = """
███████╗██████╗     ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗██╗ ██████╗██╗     ███████╗
██╔════╝██╔══██╗   ██╔════╝██║  ██║██╔══██╗██╔═══██╗████╗  ██║██║██╔════╝██║     ██╔════╝
█████╗  ██║  ██║   ██║     ███████║██████╔╝██║   ██║██╔██╗ ██║██║██║     ██║     █████╗
██╔══╝  ██║  ██║   ██║     ██╔══██║██╔══██╗██║   ██║██║╚██╗██║██║██║     ██║     ██╔══╝
███████╗██████╔╝   ╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║██║╚██████╗███████╗███████╗
╚══════╝╚═════╝     ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝ ╚═════╝╚══════╝╚══════╝
"""

BOOT_LINES = [
    ("BIOS v3.10 — CORE SYSTEMS", "#888888", 500),
    ("MEMORY CHECK.................. OK", "#666666", 550),
    ("INITIALIZING RUNTIME CORE", "#FF8C00", 600),
    ("LOADING JOURNAL ENGINE", "#E6E6E6", 550),
    ("LOADING PLANET VALUE DATABASE", "#E6E6E6", 500),
    ("LOADING EXOBIOLOGY CATALOG", "#E6E6E6", 550),
    ("LOADING POWERPLAY ACTIVITIES", "#E6E6E6", 500),
    ("LOADING COMBAT RECORDS", "#E6E6E6", 500),
    ("STARTING TTS ENGINE", "#E6E6E6", 550),
    ("CALIBRATING VOICE SYSTEMS", "#E6E6E6", 500),
    ("ESTABLISHING SENSOR ARRAY", "#E6E6E6", 550),
    ("SCANNING FOR HOSTILES", "#FF8C00", 650),
    ("CONNECTING TO JOURNAL FEED", "#FF8C00", 600),
    ("RUNNING SYSTEM DIAGNOSTICS", "#E6E6E6", 550),
    ("ALL SYSTEMS NOMINAL", "#7CFC98", 700),
    ("LAUNCHING EDCHRONICLE", "#FF8C00", 500),
]

W, H = 820, 480


# ─── Scene objects ─────────────────────────────────────────────────────────────

class _Star:
    def __init__(self, layer: int):
        self.layer = layer
        self.speed = [0.3, 0.7, 1.4][layer]
        self.size  = [1, 1, 2][layer]
        self.alpha = [60, 110, 180][layer]
        self.reset(spawn=True)

    def reset(self, spawn=False):
        self.x = random.uniform(0, W) if spawn else W + 2
        self.y = random.uniform(0, H)

    def update(self):
        self.x -= self.speed
        if self.x < 0:
            self.reset()


class _Bolt:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.speed = 9.0
        self.alive = True

    def update(self):
        self.x += self.speed
        if self.x > W + 10:
            self.alive = False


class _Particle:
    def __init__(self, x, y):
        angle = random.uniform(0, math.pi * 2)
        speed = random.uniform(1.5, 5.0)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.x = float(x)
        self.y = float(y)
        self.life = random.randint(12, 22)
        self.max_life = self.life
        self.r = random.choice([255, 255, 220, 180])
        self.g = random.choice([140, 80, 60, 40])

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vx *= 0.92
        self.vy *= 0.92
        self.life -= 1


class _Enemy:
    def __init__(self):
        self.x = float(W + 40)
        self.y = random.uniform(H * 0.55, H * 0.88)
        self.speed = random.uniform(1.0, 2.2)
        self.alive = True
        self.hit_radius = 18

    def update(self):
        self.x -= self.speed
        if self.x < -50:
            self.alive = False

    def draw(self, p: QPainter):
        sx, sy = self.x, self.y
        body_color = QColor(180, 30, 30, 160)
        wing_color = QColor(120, 20, 20, 130)
        cockpit_color = QColor(255, 80, 80, 100)

        # main hull (pointed left — enemy comes from right)
        hull = QPolygonF([
            QPointF(sx - 24, sy),       # nose (pointing left)
            QPointF(sx - 6,  sy - 6),
            QPointF(sx + 20, sy - 4),
            QPointF(sx + 24, sy),
            QPointF(sx + 20, sy + 4),
            QPointF(sx - 6,  sy + 6),
        ])
        p.setPen(QPen(QColor(220, 50, 50, 180), 1))
        p.setBrush(QBrush(body_color))
        p.drawPolygon(hull)

        # left wing
        lwing = QPolygonF([
            QPointF(sx - 2,  sy - 5),
            QPointF(sx + 14, sy - 18),
            QPointF(sx + 18, sy - 5),
            QPointF(sx + 8,  sy - 4),
        ])
        p.setBrush(QBrush(wing_color))
        p.drawPolygon(lwing)

        # right wing
        rwing = QPolygonF([
            QPointF(sx - 2,  sy + 5),
            QPointF(sx + 14, sy + 18),
            QPointF(sx + 18, sy + 5),
            QPointF(sx + 8,  sy + 4),
        ])
        p.drawPolygon(rwing)

        # cockpit
        cockpit = QPolygonF([
            QPointF(sx - 18, sy),
            QPointF(sx - 8,  sy - 4),
            QPointF(sx,      sy - 3),
            QPointF(sx,      sy + 3),
            QPointF(sx - 8,  sy + 4),
        ])
        p.setPen(QPen(QColor(255, 100, 100, 160), 1))
        p.setBrush(QBrush(cockpit_color))
        p.drawPolygon(cockpit)


# ─── Background canvas ─────────────────────────────────────────────────────────

class _BackgroundCanvas(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(W, H)
        self.raise_()

        self._stars = (
            [_Star(0) for _ in range(60)] +
            [_Star(1) for _ in range(35)] +
            [_Star(2) for _ in range(15)]
        )

        # Player ship
        self._ship_x    = -80.0
        self._ship_y    = H * 0.72
        self._ship_t    = 0.0
        self._exhaust: list = []

        # Combat
        self._bolts:     list[_Bolt]     = []
        self._enemies:   list[_Enemy]    = []
        self._particles: list[_Particle] = []
        self._fire_cd    = 0
        self._spawn_cd   = random.randint(30, 60)

        self._tick = QTimer()
        self._tick.timeout.connect(self._update)
        self._tick.start(33)

    def _update(self):
        if not self.isVisible():
            return
        # stars
        for s in self._stars:
            s.update()

        # player ship
        self._ship_t += 0.03
        self._ship_x += 1.8
        self._ship_y = H * 0.72 + math.sin(self._ship_t) * 28
        if self._ship_x > W + 80:
            self._ship_x = -80.0

        # exhaust
        if random.random() < 0.7:
            self._exhaust.append([
                self._ship_x - 28,
                self._ship_y + random.uniform(-3, 3),
                12, 12
            ])
        self._exhaust = [p for p in self._exhaust if p[2] > 0]
        for p in self._exhaust:
            p[0] -= 1.8
            p[2] -= 1

        # spawn enemies
        self._spawn_cd -= 1
        if self._spawn_cd <= 0:
            self._enemies.append(_Enemy())
            self._spawn_cd = random.randint(45, 90)

        # auto-fire at nearest enemy in rough Y range
        self._fire_cd -= 1
        if self._fire_cd <= 0 and self._enemies:
            targets = [e for e in self._enemies if abs(e.y - self._ship_y) < 60 and e.x > self._ship_x]
            if targets:
                self._bolts.append(_Bolt(self._ship_x + 28, self._ship_y))
                self._fire_cd = random.randint(14, 22)

        # update bolts
        for b in self._bolts:
            b.update()
        self._bolts = [b for b in self._bolts if b.alive]

        # update enemies
        for e in self._enemies:
            e.update()

        # collision detection
        for b in self._bolts:
            for e in self._enemies:
                if e.alive and abs(b.x - e.x) < e.hit_radius and abs(b.y - e.y) < e.hit_radius:
                    b.alive = False
                    e.alive = False
                    for _ in range(28):
                        self._particles.append(_Particle(e.x, e.y))

        self._bolts   = [b for b in self._bolts   if b.alive]
        self._enemies = [e for e in self._enemies if e.alive]

        # update particles
        for p in self._particles:
            p.update()
        self._particles = [p for p in self._particles if p.life > 0]

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # stars
        for s in self._stars:
            c = QColor(200, 200, 220, s.alpha)
            p.setPen(QPen(c, s.size))
            p.drawPoint(int(s.x), int(s.y))

        # exhaust
        for px, py, life, max_life in self._exhaust:
            ratio = life / max_life
            c = QColor(int(255 * ratio), int(60 * ratio * 0.5), 0, int(180 * ratio))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(c))
            size = max(1, int(3 * ratio))
            p.drawEllipse(int(px), int(py), size, size)

        # laser bolts
        for b in self._bolts:
            p.setPen(QPen(QColor(255, 220, 80, 220), 2))
            p.drawLine(int(b.x), int(b.y), int(b.x) - 14, int(b.y))
            p.setPen(QPen(QColor(255, 255, 180, 80), 1))
            p.drawLine(int(b.x), int(b.y) - 1, int(b.x) - 14, int(b.y) - 1)

        # explosion particles
        for pt in self._particles:
            ratio = pt.life / pt.max_life
            c = QColor(pt.r, pt.g, 0, int(200 * ratio))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(c))
            size = max(1, int(4 * ratio))
            p.drawEllipse(int(pt.x), int(pt.y), size, size)

        # enemies
        for e in self._enemies:
            e.draw(p)

        # player ship
        sx, sy = self._ship_x, self._ship_y
        hull = QPolygonF([
            QPointF(sx + 28, sy),
            QPointF(sx + 8,  sy - 7),
            QPointF(sx - 22, sy - 5),
            QPointF(sx - 28, sy),
            QPointF(sx - 22, sy + 5),
            QPointF(sx + 8,  sy + 7),
        ])
        p.setPen(QPen(QColor(255, 140, 0, 160), 1))
        p.setBrush(QBrush(QColor(180, 100, 0, 130)))
        p.drawPolygon(hull)

        cockpit = QPolygonF([
            QPointF(sx + 20, sy),
            QPointF(sx + 10, sy - 5),
            QPointF(sx + 2,  sy - 4),
            QPointF(sx + 2,  sy + 4),
            QPointF(sx + 10, sy + 5),
        ])
        p.setBrush(QBrush(QColor(255, 200, 80, 80)))
        p.setPen(QPen(QColor(255, 200, 80, 140), 1))
        p.drawPolygon(cockpit)

        lwing = QPolygonF([
            QPointF(sx + 4,  sy - 6),
            QPointF(sx - 18, sy - 18),
            QPointF(sx - 24, sy - 4),
            QPointF(sx - 10, sy - 4),
        ])
        p.setPen(QPen(QColor(255, 140, 0, 160), 1))
        p.setBrush(QBrush(QColor(100, 60, 0, 100)))
        p.drawPolygon(lwing)

        rwing = QPolygonF([
            QPointF(sx + 4,  sy + 6),
            QPointF(sx - 18, sy + 18),
            QPointF(sx - 24, sy + 4),
            QPointF(sx - 10, sy + 4),
        ])
        p.drawPolygon(rwing)

        p.end()

    def stop(self):
        self._tick.stop()
        self._tick.deleteLater()
        self.hide()


# ─── Splash screen ─────────────────────────────────────────────────────────────

class SplashScreen(QWidget):

    def __init__(self, on_done, import_runner=None):
        super().__init__()
        self._on_done = on_done
        self._line_index = 0
        self._cursor_visible = True

        self._import_runner = import_runner
        self._import_thread: threading.Thread | None = None
        self._import_current = 0
        self._import_total = 0
        self._import_done = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(W, H)
        self._center()
        self.setStyleSheet("background-color: #000000;")

        self._canvas = _BackgroundCanvas(self)
        self._canvas.lower()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(4)

        self._header = QLabel(ASCII_HEADER)
        self._header.setFont(QFont("Courier New", 5, QFont.Weight.Bold))
        self._header.setStyleSheet("color: #FF8C00; background: transparent;")
        self._header.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._header)

        sep = QLabel("─" * 100)
        sep.setFont(QFont("Courier New", 8))
        sep.setStyleSheet("color: #333333; background: transparent;")
        layout.addWidget(sep)

        layout.addSpacing(6)

        self._log_labels = []
        for _ in BOOT_LINES:
            lbl = QLabel("")
            lbl.setFont(QFont("Courier New", 9))
            lbl.setStyleSheet("background: transparent;")
            layout.addWidget(lbl)
            self._log_labels.append(lbl)

        layout.addStretch()

        self._cursor_label = QLabel("_")
        self._cursor_label.setFont(QFont("Courier New", 10))
        self._cursor_label.setStyleSheet("color: #FF8C00; background: transparent;")
        layout.addWidget(self._cursor_label)

        self._import_label = QLabel("")
        self._import_label.setFont(QFont("Courier New", 9))
        self._import_label.setStyleSheet("color: #FF8C00; background: transparent;")
        self._import_label.setVisible(False)
        layout.addWidget(self._import_label)

        self._cursor_timer = QTimer()
        self._cursor_timer.timeout.connect(self._blink_cursor)
        self._cursor_timer.start(500)

        self._line_timer = QTimer()
        self._line_timer.setSingleShot(True)
        self._line_timer.timeout.connect(self._advance_line)
        self._line_timer.start(1000)

        self._import_poll = QTimer()
        self._import_poll.timeout.connect(self._poll_import)
        self._import_poll.start(150)

        if self._import_runner is not None:
            self._start_import_thread()

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )

    def _blink_cursor(self):
        self._cursor_visible = not self._cursor_visible
        self._cursor_label.setText("_" if self._cursor_visible else " ")

    def _advance_line(self):
        if self._line_index >= len(BOOT_LINES):
            QTimer.singleShot(900, self._finish)
            return

        text, color, delay = BOOT_LINES[self._line_index]
        lbl = self._log_labels[self._line_index]
        lbl.setText(f"> {text}")
        lbl.setStyleSheet(f"color: {color}; background: transparent;")

        self._line_index += 1
        jitter = random.randint(-50, 50)
        self._line_timer.start(delay + jitter)

    def _start_import_thread(self):
        def _run():
            try:
                self._import_runner(self._on_import_progress)
            except Exception:
                log.exception("Journal import failed in splash thread")
            finally:
                self._import_done = True

        self._import_thread = threading.Thread(target=_run, daemon=True)
        self._import_thread.start()

    def _on_import_progress(self, current: int, total: int):
        self._import_current = current
        self._import_total = total

    def _poll_import(self):
        if self._import_thread is None:
            return
        total = self._import_total
        current = self._import_current
        if total > 0:
            self._import_label.setVisible(True)
            if self._import_done:
                self._import_label.setText(f"> JOURNALS READY  [ {total} / {total} ]")
            else:
                self._import_label.setText(f"> IMPORTING JOURNALS... [ {current} / {total} ]")

    def _finish(self):
        self._cursor_timer.stop()
        self._line_timer.stop()
        self._canvas.stop()

        if self._import_thread is not None:
            self._wait_for_import()
        else:
            QTimer.singleShot(300, self._launch)

    def _wait_for_import(self):
        if self._import_done:
            self._import_poll.stop()
            total = self._import_total
            self._import_label.setVisible(True)
            self._import_label.setText(f"> JOURNALS READY  [ {total} / {total} ]")
            QTimer.singleShot(1000, self._launch)
        else:
            QTimer.singleShot(200, self._wait_for_import)

    def _launch(self):
        self._import_poll.stop()
        self.close()
        self._on_done()
