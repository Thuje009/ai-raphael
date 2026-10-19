import sys
import math
import time
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QRadialGradient, QPen
from PyQt6.QtWidgets import QApplication, QWidget

class WidgetController(QObject):
    state_signal = pyqtSignal(str)

class RaphaelWidget(QWidget):
    def __init__(self, controller: WidgetController):
        super().__init__()
        self.controller = controller
        self.controller.state_signal.connect(self.change_state_slot)
        self.initUI()
        
    def initUI(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        self.setFixedSize(220, 220)
        self.current_state = "hidden" # เริ่มต้นซ่อนตัวสนิท
        self.animation_step = 0.0
        
        self.move_to_bottom_right()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)

    def move_to_bottom_right(self):
        screen = QApplication.primaryScreen().geometry()
        margin = 30
        x = screen.width() - self.width() - margin
        y = screen.height() - self.height() - margin
        self.move(x, y)

    def change_state_slot(self, state):
        self.current_state = state
        if state == "hidden":
            self.hide()
        else:
            self.show()
        self.update()

    def update_animation(self):
        if self.current_state != "hidden":
            self.animation_step += 0.1
            self.update()

    def paintEvent(self, event):
        if self.current_state == "hidden":
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        cx, cy = self.width() / 2, self.height() / 2

        # 1. กำลังฟังเสียง (Listening) - สีฟ้า + คลื่นกระเพื่อม
        if self.current_state == "listening":
            pen = QPen()
            pen.setWidth(2)
            for i in range(3):
                alpha = int(150 - (i * 40) + 50 * math.sin(self.animation_step * 2 - i))
                pen.setColor(QColor(0, 160, 255, max(0, min(255, alpha))))
                painter.setPen(pen)
                offset = 25 + (i * 12)
                painter.drawArc(int(cx - offset - 20), int(cy - 30), 40, 60, 60 * 16, 240 * 16)
                painter.drawArc(int(cx + offset - 20), int(cy - 30), 40, 60, 240 * 16, 240 * 16)

            self.draw_sphere(painter, cx, cy, QColor(0, 130, 255), QColor(0, 200, 255))

        # 2. กำลังคิด / แปลภาษา (Thinking) - สีม่วง + วงแหวนวงโคจร
        elif self.current_state == "thinking":
            painter.setPen(QPen(QColor(200, 100, 255, 120), 1.5))
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(self.animation_step * 30)
            painter.drawEllipse(-45, -20, 90, 40)
            painter.rotate(45)
            painter.drawEllipse(-45, -20, 90, 40)
            painter.restore()

            self.draw_sphere(painter, cx, cy, QColor(140, 0, 220), QColor(220, 100, 255))

        # 3. กำลังพูดตอบ (Speaking) - สีเขียว + วงแหวนขยายออก
        elif self.current_state == "speaking":
            for i in range(2):
                radius = 45 + (i * 20) + (math.sin(self.animation_step * 3) * 5)
                alpha = int(100 - (i * 40))
                painter.setPen(QPen(QColor(50, 255, 120, max(0, alpha)), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), radius, radius)

            pulse_size = 35 + int(3 * math.sin(self.animation_step * 5))
            self.draw_sphere(painter, cx, cy, QColor(0, 180, 80), QColor(100, 255, 150), radius=pulse_size)

    def draw_sphere(self, painter, cx, cy, base_color, glow_color, radius=35):
        gradient_glow = QRadialGradient(cx, cy, radius * 1.8)
        gradient_glow.setColorAt(0, glow_color)
        gradient_glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(gradient_glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.8, radius * 1.8)

        gradient_sphere = QRadialGradient(cx - 8, cy - 8, radius)
        gradient_sphere.setColorAt(0, glow_color)
        gradient_sphere.setColorAt(0.7, base_color)
        gradient_sphere.setColorAt(1, QColor(10, 10, 30))
        painter.setBrush(gradient_sphere)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


# ตัวแปรควบคุมส่วนกลาง
_global_app = None
_global_controller = None

def start_widget_thread():
    """รัน Qt App ใน Background Thread อย่างถูกต้องโดยไม่บล็อก Main Thread ของเสียง"""
    import threading
    def run():
        global _global_app, _global_controller
        _global_app = QApplication(sys.argv)
        _global_controller = WidgetController()
        widget = RaphaelWidget(_global_controller)
        _global_controller.state_signal.emit("hidden") # เริ่มต้นซ่อนตัว
        _global_app.exec()

    t = threading.Thread(target=run, daemon=True)
    t.start()

def set_widget_state(state):
    """ฟังก์ชันสั่งเปลี่ยนสถานะ ('listening', 'thinking', 'speaking', 'hidden')"""
    global _global_controller
    if _global_controller:
        _global_controller.state_signal.emit(state)