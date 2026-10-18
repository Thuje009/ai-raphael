import threading

# ใช้ครอบทุกจุดที่แตะเมาส์/คีย์บอร์ดผ่าน pyautogui
# เพื่อไม่ให้ตัวข้ามโฆษณา (thread แยก) คลิกแทรกตอนกำลังพิมพ์ URL หรือข้อความ
GUI_LOCK = threading.RLock()