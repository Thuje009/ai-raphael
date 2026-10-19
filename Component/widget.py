import sys
import math
import time
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QObject
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QConicalGradient, QPen, QFont, QPolygonF
)
from PyQt6.QtWidgets import QApplication, QWidget

# สีประจำสถานะ (R, G, B)
STATE_COLORS = {
    "listening": (0, 200, 255),    # ฟ้าไซเบอร์
    "thinking":  (180, 100, 255),  # ม่วงนีออน
    "speaking":  (60, 255, 140),   # เขียวพลังงาน
}
STATE_LABELS = {
    "listening": "LISTENING",
    "thinking": "ANALYZING",
    "speaking": "RESPONDING",
}


class WidgetController(QObject):
    state_signal = pyqtSignal(str)


class RaphaelWidget(QWidget):
    SIZE = 260

    def __init__(self, controller: WidgetController):
        super().__init__()
        self.controller = controller
        self.controller.state_signal.connect(self.change_state_slot)
        self.initUI()

    def initUI(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(self.SIZE, self.SIZE)

        self.current_state = "hidden"
        self.label_text = ""

        # ค่าที่ถูกทำให้นุ่มนวล (smooth) ทุกเฟรม
        self.t = 0.0
        self.alpha = 0.0
        self.target_alpha = 0.0
        self.color = [0.0, 200.0, 255.0]
        self.target_color = [0.0, 200.0, 255.0]
        self.k = {"listening": 0.0, "thinking": 0.0, "speaking": 0.0}

        # มุมหมุนสะสมของแต่ละวง
        self.ang_outer = 0.0
        self.ang_mid = 0.0
        self.ang_inner = 0.0
        self.ang_scan = 0.0

        self.move_to_bottom_right()

        self._last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)  # ~60 FPS

    # ---------- ตำแหน่ง / สถานะ ----------
    def move_to_bottom_right(self):
        screen = QApplication.primaryScreen().geometry()
        margin = 20
        x = screen.width() - self.width() - margin
        y = screen.height() - self.height() - margin
        self.move(x, y)

    def change_state_slot(self, state):
        self.current_state = state
        if state == "hidden":
            self.target_alpha = 0.0
        else:
            self.target_alpha = 1.0
            self.target_color = list(map(float, STATE_COLORS.get(state, (0, 200, 255))))
            self.label_text = STATE_LABELS.get(state, "")
            if not self.isVisible():
                self.show()

    # ---------- แอนิเมชัน ----------
    def update_animation(self):
        now = time.perf_counter()
        dt = min(now - self._last, 0.05)
        self._last = now
        if self.current_state == "hidden" and self.alpha <= 0.005:
            if self.isVisible():
                self.hide()
            return

        self.t += dt
        f = 1.0 - math.exp(-dt * 7.0)  # ease-out แบบ exponential

        self.alpha += (self.target_alpha - self.alpha) * f
        for i in range(3):
            self.color[i] += (self.target_color[i] - self.color[i]) * f
        for name in self.k:
            target = 1.0 if self.current_state == name else 0.0
            self.k[name] += (target - self.k[name]) * f

        think = self.k["thinking"]
        self.ang_outer += dt * (14 + 40 * think)
        self.ang_mid -= dt * (28 + 120 * think)
        self.ang_inner += dt * (45 + 200 * think)
        self.ang_scan += dt * (90 + 260 * think)
        self.update()

    # ---------- วาด ----------
    def _c(self, a=255, lighten=0):
        r, g, b = (min(255, int(v + lighten)) for v in self.color)
        return QColor(r, g, b, max(0, min(255, int(a))))

    def paintEvent(self, event):
        if self.alpha <= 0.005:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self.alpha)))

        cx, cy = self.width() / 2, self.height() / 2
        t = self.t

        self._draw_ambient(p, cx, cy)
        self._draw_scan(p, cx, cy)
        self._draw_speaking_pulses(p, cx, cy)
        self._draw_tick_ring(p, cx, cy, 92)
        self._draw_segment_ring(p, cx, cy, 80)
        self._draw_mid_arcs(p, cx, cy, 66)
        self._draw_listening_bars(p, cx, cy, 52)
        self._draw_data_nodes(p, cx, cy, 74)
        self._draw_core(p, cx, cy)
        p.end()

    def _draw_ambient(self, p, cx, cy):
        g = QRadialGradient(cx, cy, 110)
        g.setColorAt(0.0, self._c(70))
        g.setColorAt(0.6, self._c(18))
        g.setColorAt(1.0, self._c(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), 110, 110)

    def _draw_scan(self, p, cx, cy):
        k = self.k["thinking"]
        if k < 0.01:
            return
        g = QConicalGradient(cx, cy, -self.ang_scan)
        g.setColorAt(0.0, self._c(150 * k, 40))
        g.setColorAt(0.18, self._c(0))
        g.setColorAt(1.0, self._c(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), 78, 78)

    def _draw_speaking_pulses(self, p, cx, cy):
        k = self.k["speaking"]
        if k < 0.01:
            return
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            phase = (self.t * 0.8 + i / 3) % 1.0
            r = 36 + phase * 58
            a = (1.0 - phase) ** 1.5 * 190 * k
            p.setPen(QPen(self._c(a, 30), 1.6))
            p.drawEllipse(QPointF(cx, cy), r, r)

    def _draw_tick_ring(self, p, cx, cy, r):
        p.save()
        p.translate(cx, cy)
        p.rotate(self.ang_outer)
        for i in range(72):
            major = i % 6 == 0
            p.setPen(QPen(self._c(170 if major else 70), 1.4 if major else 1))
            ln = 7 if major else 3
            p.drawLine(QPointF(0, -r), QPointF(0, -r + ln))
            p.rotate(5)
        p.restore()

    def _draw_segment_ring(self, p, cx, cy, r):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._c(110), 1.2))
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        base = -self.ang_mid * 0.5
        # วงแบ่งเป็น 4 ท่อน ช่องว่างไม่เท่ากัน
        for i, (start, span) in enumerate([(0, 70), (90, 50), (180, 70), (270, 30)]):
            p.drawArc(rect, int((base + start) * 16), int(span * 16))

    def _draw_mid_arcs(self, p, cx, cy, r):
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(self._c(230, 40), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.drawArc(rect, int(self.ang_mid * 16), int(55 * 16))
        p.drawArc(rect, int((self.ang_mid + 180) * 16), int(55 * 16))
        p.setPen(QPen(self._c(90), 1))
        r2 = r - 7
        rect2 = QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2)
        p.drawArc(rect2, int(self.ang_inner * 16), int(120 * 16))
        p.drawArc(rect2, int((self.ang_inner + 180) * 16), int(120 * 16))

    def _draw_listening_bars(self, p, cx, cy, r):
        k = self.k["listening"]
        if k < 0.01:
            return
        n = 48
        p.save()
        p.translate(cx, cy)
        for i in range(n):
            wave = (0.5 + 0.5 * math.sin(self.t * 4.2 + i * 0.7)) * \
                   (0.5 + 0.5 * math.sin(self.t * 2.1 + i * 1.9))
            ln = (3 + 13 * wave) * k
            p.setPen(QPen(self._c(80 + 160 * wave, 30), 1.8))
            p.drawLine(QPointF(0, -r), QPointF(0, -r - ln))
            p.rotate(360 / n)
        p.restore()

    def _draw_data_nodes(self, p, cx, cy, r):
        p.setPen(Qt.PenStyle.NoPen)
        speed = 1.0 + 2.5 * self.k["thinking"]
        for i in range(5):
            a = math.radians(self.t * 40 * speed * (1 if i % 2 == 0 else -0.7) + i * 72)
            rr = r + (i % 3) * 3
            x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
            p.setBrush(self._c(240, 60))
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
            p.setBrush(self._c(50))
            p.drawEllipse(QPointF(x, y), 5, 5)

    def _draw_core(self, p, cx, cy):
        breathe = math.sin(self.t * 2.0)
        radius = 24 + 1.5 * breathe + self.k["speaking"] * 3.5 * math.sin(self.t * 9)

        glow = QRadialGradient(cx, cy, radius * 2.2)
        glow.setColorAt(0.0, self._c(200, 40))
        glow.setColorAt(0.5, self._c(60))
        glow.setColorAt(1.0, self._c(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), radius * 2.2, radius * 2.2)

        body = QRadialGradient(cx - 6, cy - 7, radius * 1.1)
        body.setColorAt(0.0, QColor(240, 250, 255, 255))
        body.setColorAt(0.35, self._c(255, 50))
        body.setColorAt(1.0, QColor(6, 12, 28, 255))
        p.setBrush(body)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # หกเหลี่ยมหมุนในแกนกลาง
        p.save()
        p.translate(cx, cy)
        p.rotate(-self.ang_inner * 0.6)
        hexa = QPolygonF([
            QPointF((radius - 6) * math.cos(math.radians(60 * i)),
                    (radius - 6) * math.sin(math.radians(60 * i)))
            for i in range(6)
        ])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
        p.drawPolygon(hexa)
        p.restore()

        p.setPen(QPen(self._c(255, 60), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius, radius)


# ตัวแปรควบคุมส่วนกลาง
_global_app = None
_global_controller = None


def start_widget_thread():
    """รัน Qt App ใน Background Thread อย่างถูกต้องโดยไม่บล็อก Main Thread ของเสียง"""
    import threading

    def run():
        global _global_app, _global_controller
        _global_app = QApplication(sys.argv)
        _global_app.setQuitOnLastWindowClosed(False)
        _global_controller = WidgetController()
        widget = RaphaelWidget(_global_controller)  # noqa: F841 (ต้องถือ reference ไว้)
        _global_controller.state_signal.emit("hidden")
        _global_app.exec()

    t = threading.Thread(target=run, daemon=True)
    t.start()


def set_widget_state(state):
    """ฟังก์ชันสั่งเปลี่ยนสถานะ ('listening', 'thinking', 'speaking', 'hidden')"""
    global _global_controller
    if _global_controller:
        _global_controller.state_signal.emit(state)