"""ระบบจัดการคำสั่งชุด (Custom Macros) ของราฟาเอล"""
import os
import time
import pyautogui
from speech import speak
from common import GUI_LOCK

# กำหนดชุดคำสั่งลัดตามต้องการ (สามารถเพิ่ม/ลดได้อิสระ)
MACROS = {
    "ทำงาน": {
        "description": "เปิดโหมดทำงาน (VS Code, Chrome, และเปิดเพลง)",
        "actions": [
            ("กำลังเปิด Visual Studio Code ให้ค่ะ", lambda: os.system("start code")),
            ("กำลังเปิด Google Chrome ให้ค่ะ", lambda: os.system("start chrome")),
            ("กำลังเปิดเพลงฟังสบายๆ ให้ค่ะ", lambda: os.system("start chrome https://www.youtube.com/watch?v=5qap5aO4i9A")),
        ]
    },
    "พักผ่อน": {
        "description": "เปิดโหมดพักผ่อน (ปิดหน้าต่างอื่น เปิด YouTube)",
        "actions": [
            ("กำลังเปิด YouTube ให้ค่ะ", lambda: os.system("start chrome https://www.youtube.com")),
        ]
    }
}

def run_macro(macro_name):
    """ค้นหาและรันชุดคำสั่งตามชื่อที่ระบุ"""
    # คีย์เวิร์ดเทียบหาชุดคำสั่ง
    matched_key = None
    for key in MACROS:
        if key in macro_name:
            matched_key = key
            break
            
    if not matched_key:
        speak("ไม่พบชุดคำสั่งที่ระบุค่ะ")
        return False
        
    macro = MACROS[matched_key]
    speak(f"กำลังเริ่มชุดคำสั่ง {matched_key} ค่ะ")
    
    for message, action in macro["actions"]:
        if message:
            speak(message)
        with GUI_LOCK:
            action()
        time.sleep(0.5)
        
    speak(f"ทำชุดคำสั่ง {matched_key} เรียบร้อยแล้วค่ะ")
    return True