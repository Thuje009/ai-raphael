"""หน้าต่างตั้งค่าเริ่มต้นระบบ (Setup Wizard) สำหรับผู้ใช้ใหม่ - ธีม Sci-Fi HUD"""
import sys
import json
import os
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QPainterPath,
    QRadialGradient, QLinearGradient
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QFrame,
    QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox, QCheckBox
)

CONFIG_FILE = "config.json"

ACCENT = QColor(34, 211, 238)  # ไซแอน นีออน


class AnimatedCore(QWidget):
    """แกนพลังงานเล็กๆ ด้านบนหน้าต่าง สไตล์เดียวกับวิดเจ็ตผู้ช่วย"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(120, 120)
        self.a = 0.0
        self.t = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def _tick(self):
        self.a += 1.0
        self.t += 0.016
        self.update()

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = 60

        glow = QRadialGradient(cx, cy, 58)
        glow.setColorAt(0.0, QColor(34, 211, 238, 70))
        glow.setColorAt(1.0, QColor(34, 211, 238, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), 58, 58)

        # วงสเกลขีด
        p.save()
        p.translate(cx, cy)
        p.rotate(self.a * 0.3)
        for i in range(48):
            major = i % 4 == 0
            p.setPen(QPen(QColor(34, 211, 238, 170 if major else 70), 1.3 if major else 1))
            p.drawLine(QPointF(0, -53), QPointF(0, -53 + (6 if major else 3)))
            p.rotate(7.5)
        p.restore()

        # ส่วนโค้งหมุนสวนทางกัน
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = 41
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setPen(QPen(QColor(103, 232, 249, 235), 2.4))
        p.drawArc(rect, int(-self.a * 1.4 * 16), int(70 * 16))
        p.drawArc(rect, int((-self.a * 1.4 + 180) * 16), int(70 * 16))
        r = 32
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setPen(QPen(QColor(34, 211, 238, 110), 1.2))
        p.drawArc(rect, int(self.a * 2.4 * 16), int(120 * 16))
        p.drawArc(rect, int((self.a * 2.4 + 180) * 16), int(120 * 16))

        # แกนกลาง
        rad = 13 + 1.2 * math.sin(self.t * 2.2)
        body = QRadialGradient(cx - 3, cy - 4, rad * 1.1)
        body.setColorAt(0.0, QColor(240, 252, 255))
        body.setColorAt(0.4, QColor(34, 211, 238))
        body.setColorAt(1.0, QColor(6, 20, 40))
        p.setPen(QPen(QColor(165, 243, 252, 200), 1.2))
        p.setBrush(body)
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.end()


class SetupWizard(QWidget):
    def __init__(self):
        super().__init__()
        self.is_success = False
        self._drag_offset = None
        self.initUI()

    # ---------- ตัวช่วยสร้างส่วนประกอบ ----------
    @staticmethod
    def _tag(text, color="#22d3ee", size=10):
        """ป้ายข้อความ monospace แบบ HUD (QSS ไม่รองรับ letter-spacing จึงตั้งผ่าน QFont)"""
        lbl = QLabel(text)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(size)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    def _field_header(self, index, text, link_url=None):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._tag(index))
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        row.addWidget(label)
        row.addStretch()
        if link_url:
            link = QLabel(
                f'<a href="{link_url}" style="color:#38bdf8; text-decoration:none;">[ ขอ API Key ]</a>'
            )
            link.setOpenExternalLinks(True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(link)
        return row

    # ---------- สร้างหน้าต่าง ----------
    def initUI(self):
        self.setWindowTitle("AI Assistant - First Time Setup")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(480, 780)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        self.setStyleSheet("""
            QWidget {
                background: transparent;
                color: #cbd5e1;
                font-family: 'Segoe UI', 'Noto Sans Thai', Arial, sans-serif;
                font-size: 13px;
            }
            QLabel#Title { color: #f1f5f9; font-size: 21px; font-weight: 700; }
            QLabel#Sub { color: #64748b; font-size: 12px; }
            QLabel#FieldLabel { color: #94a3b8; font-weight: 600; }
            QFrame#Divider { background: rgba(34, 211, 238, 60); max-height: 1px; min-height: 1px; border: none; }
            QLineEdit {
                background: rgba(15, 23, 42, 210);
                border: 1px solid #1e3a4c;
                border-radius: 8px;
                padding: 10px 12px;
                color: #e2e8f0;
                selection-background-color: #0e7490;
            }
            QLineEdit:hover { border: 1px solid #2a5a73; }
            QLineEdit:focus { border: 1px solid #22d3ee; background: rgba(8, 47, 73, 150); }
            QCheckBox { color: #cbd5e1; spacing: 10px; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                border: 1px solid #22d3ee; border-radius: 4px;
                background: rgba(15, 23, 42, 210);
            }
            QCheckBox::indicator:checked {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 #a5f3fc, stop:0.5 #22d3ee, stop:0.56 rgba(8, 47, 73, 220), stop:1 rgba(8, 47, 73, 220));
            }
            QPushButton#Primary {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891b2, stop:1 #2563eb);
                color: white;
                border: 1px solid #22d3ee;
                border-radius: 8px;
                padding: 13px;
                font-weight: 700;
                font-size: 14px;
            }
            QPushButton#Primary:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #3b82f6);
                border: 1px solid #a5f3fc;
            }
            QPushButton#Primary:pressed { background: #0e7490; }
            QPushButton#Close {
                background: transparent; color: #64748b; border: none;
                font-size: 15px; padding: 2px 8px;
            }
            QPushButton#Close:hover { color: #f87171; }
            QMessageBox, QDialog { background-color: #0a1222; }
            QMessageBox QLabel { color: #e2e8f0; }
            QMessageBox QPushButton {
                background: #0e7490; color: white; border: 1px solid #22d3ee;
                border-radius: 6px; padding: 6px 18px; min-width: 70px;
            }
            QMessageBox QPushButton:hover { background: #0891b2; }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(38, 24, 38, 30)

        # แถบบน: สถานะระบบ + ปุ่มปิด
        top = QHBoxLayout()
        top.addWidget(self._tag("SYS.BOOT // FIRST-TIME SETUP", "#64748b", 9))
        top.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        top.addWidget(close_btn)
        layout.addLayout(top)

        # แกนแอนิเมชัน + หัวข้อ
        self.core = AnimatedCore()
        layout.addWidget(self.core, alignment=Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("INITIALIZE AI ASSISTANT")
        title.setObjectName("Title")
        tf = title.font()
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("กรุณาตั้งค่าระบบเบื้องต้นก่อนเริ่มต้นใช้งานครั้งแรก")
        sub.setObjectName("Sub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        divider = QFrame()
        divider.setObjectName("Divider")
        layout.addWidget(divider)

        # 01 ชื่อผู้ช่วย
        layout.addLayout(self._field_header("01", "ชื่อผู้ช่วยของคุณ (Assistant Name)"))
        self.name_input = QLineEdit()
        self.name_input.setText("ราฟาเอล")
        layout.addWidget(self.name_input)

        # 02 Groq
        layout.addLayout(self._field_header("02", "Groq API Key", "https://console.groq.com/keys"))
        self.groq_input = QLineEdit()
        self.groq_input.setPlaceholderText("gsk_...")
        self.groq_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.groq_input)

        # 03 Gemini
        layout.addLayout(self._field_header("03", "Gemini API Key (ใส่ช่องใดช่องหนึ่งได้)",
                                            "https://aistudio.google.com/app/apikey"))
        self.gemini_input = QLineEdit()
        self.gemini_input.setPlaceholderText("AIzaSy...")
        self.gemini_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.gemini_input)

        self.show_keys_chk = QCheckBox("แสดง API Key")
        self.show_keys_chk.toggled.connect(self._toggle_keys)
        layout.addWidget(self.show_keys_chk)

        divider2 = QFrame()
        divider2.setObjectName("Divider")
        layout.addWidget(divider2)

        # 04 สิทธิ์ระบบ
        layout.addWidget(self._tag("04  PERMISSION"))
        self.permission_chk = QCheckBox(
            "ยินยอมให้ผู้ช่วยเข้าถึงระบบคอมพิวเตอร์\n(ควบคุมเมาส์, ข้ามโฆษณา, และคัดลอกข้อความ)"
        )
        layout.addWidget(self.permission_chk)

        layout.addStretch()

        self.submit_btn = QPushButton("ยืนยันและเริ่มใช้งาน  ▸")
        self.submit_btn.setObjectName("Primary")
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setDefault(True)
        self.submit_btn.clicked.connect(self.save_and_exit)
        layout.addWidget(self.submit_btn)

        footer = self._tag(f"STORAGE // LOCAL {CONFIG_FILE}", "#475569", 8)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        self.setLayout(layout)

    def _toggle_keys(self, show):
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.groq_input.setEchoMode(mode)
        self.gemini_input.setEchoMode(mode)

    # ---------- วาดพื้นหลังหน้าต่าง ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        # เรืองแสงรอบกรอบ
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in [(10, 8), (6, 16), (3, 30)]:
            p.setPen(QPen(QColor(34, 211, 238, alpha), width))
            p.drawPath(path)

        # พื้นหลังไล่สี
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0.0, QColor(10, 18, 34, 248))
        bg.setColorAt(1.0, QColor(4, 8, 16, 250))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawPath(path)

        # ตารางกริดจางๆ
        p.save()
        p.setClipPath(path)
        p.setPen(QPen(QColor(34, 211, 238, 9), 1))
        step = 32
        x = int(rect.left())
        while x < rect.right():
            p.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += step
        y = int(rect.top())
        while y < rect.bottom():
            p.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += step
        p.restore()

        # แสงไล่ด้านบน
        top_glow = QRadialGradient(rect.center().x(), rect.top() + 70, 260)
        top_glow.setColorAt(0.0, QColor(34, 211, 238, 28))
        top_glow.setColorAt(1.0, QColor(34, 211, 238, 0))
        p.setBrush(top_glow)
        p.drawPath(path)

        # เส้นขอบ
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(34, 211, 238, 150), 1.2))
        p.drawPath(path)
        p.end()

    # ---------- ลากหน้าต่าง (ไม่มีแถบชื่อ) ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    # ---------- บันทึก ----------
    def save_and_exit(self):
        if not self.permission_chk.isChecked():
            QMessageBox.warning(self, "ไม่อนุญาตสิทธิ์",
                                "คุณต้องยินยอมการเข้าถึงระบบคอมพิวเตอร์จึงจะสามารถใช้งานผู้ช่วยนี้ได้ครับ")
            return

        bot_name = self.name_input.text().strip()
        groq_key = self.groq_input.text().strip()
        gemini_key = self.gemini_input.text().strip()

        if not bot_name:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาตั้งชื่อผู้ช่วยด้วยครับ")
            return

        if not groq_key and not gemini_key:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณากรอก API Key อย่างน้อย 1 ช่อง (Groq หรือ Gemini)")
            return

        config_data = {
            "first_run": False,
            "assistant_name": bot_name,
            "wake_words": [bot_name, f"{bot_name}ครับ", f"{bot_name}คะ"],
            "groq_api_key": groq_key,
            "gemini_api_key": gemini_key,
            "permission_granted": True
        }

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            self.is_success = True
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "เกิดข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ตั้งค่าได้: {e}")


def run_setup_wizard_if_needed():
    """ตรวจสอบว่ารันครั้งแรกหรือไม่ ถ้าใช่ให้เปิดหน้าต่าง Setup Wizard"""
    config_exists = os.path.exists(CONFIG_FILE)
    is_first_run = True

    if config_exists:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                is_first_run = data.get("first_run", True)
        except Exception:
            is_first_run = True

    if is_first_run:
        app = QApplication(sys.argv)
        wizard = SetupWizard()
        wizard.show()
        app.exec()

        # ถ้าไม่ได้กดบันทึกหรือปิดหน้าต่างหนี ให้จบโปรแกรมทันที
        if not wizard.is_success:
            sys.exit(0)