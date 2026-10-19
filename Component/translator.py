"""ระบบคัดลอกข้อความและแปลภาษาของราฟาเอล"""
import time
import pyautogui
import pyperclip
import llm
from common import GUI_LOCK
from speech import speak

MAX_CHARS = 1500  # ยาวกว่านี้จะตัดทิ้ง กันพูดยาวเกินและกันส่งข้อความมหาศาลเข้า LLM

# ข้อความที่แสดงว่าผู้ใช้เผลอลากเลือก "log ของราฟาเอลเอง" ในหน้าต่างคอนโซล
_OWN_LOG_MARKERS = ("กำลังสแตนด์บาย", "กำลังวิเคราะห์คำสั่ง", "ระดับเสียงสูงสุด", "🧠", "🎙️")


def _thai_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    thai = [c for c in letters if "\u0e00" <= c <= "\u0e7f"]
    return len(thai) / len(letters)


def _grab_selection(timeout=1.0):
    """คัดลอกข้อความที่เลือกอยู่ แล้วคืนค่า (ข้อความ, คลิปบอร์ดเดิม)
    เคลียร์คลิปบอร์ดก่อนคัดลอก เพื่อให้รู้แน่ว่าได้ข้อความใหม่ ไม่ใช่ของเก่าที่ค้างอยู่"""
    try:
        old_clip = pyperclip.paste()
    except Exception:
        old_clip = ""

    pyperclip.copy("")
    with GUI_LOCK:
        pyautogui.hotkey("ctrl", "c")

    text = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.1)
        text = pyperclip.paste().strip()
        if text:
            break
    return text, old_clip


def translate_selected_text():
    selected_text, old_clip = _grab_selection()

    # คืนคลิปบอร์ดเดิมของผู้ใช้ทันที ข้อความที่แปลจึงไม่ค้างในคลิปบอร์ด
    # (แทนการรอ 5 นาทีแล้วลบทิ้ง ซึ่งอาจลบของที่ผู้ใช้เพิ่งคัดลอกใหม่)
    try:
        pyperclip.copy(old_clip)
    except Exception:
        pass

    if len(selected_text) < 2:
        speak("ไม่พบข้อความที่เลือกค่ะ กรุณาลากคลุมข้อความที่ต้องการแปลก่อนสั่งนะคะ")
        return

    if any(m in selected_text for m in _OWN_LOG_MARKERS):
        speak("ข้อความที่เลือกเป็นบันทึกการทำงานของดิฉันเองค่ะ กรุณาเลือกข้อความที่ต้องการแปลจากหน้าต่างอื่นนะคะ")
        return

    if _thai_ratio(selected_text) > 0.5:
        speak("ข้อความที่เลือกเป็นภาษาไทยอยู่แล้วค่ะ")
        return

    if len(selected_text) > MAX_CHARS:
        selected_text = selected_text[:MAX_CHARS]
        speak("ข้อความยาวมากค่ะ ดิฉันจะแปลเฉพาะช่วงต้นนะคะ")
    else:
        speak("กำลังแปลภาษาให้ค่ะ")

    prompt = f"""แปลข้อความต่อไปนี้เป็นภาษาไทยให้อ่านเข้าใจง่าย สละสลวย และตรงประเด็น:
"{selected_text}"
คำตอบไม่ต้องมีคำเกริ่น นำเสนอผลการแปลทันที"""

    try:
        translated = llm.ask(prompt, history=[], tier="fast")
        reply = translated.get("answer") if isinstance(translated, dict) else str(translated)
        if reply and reply.strip():
            speak(reply.strip())
        else:
            speak("แปลภาษาไม่สำเร็จในขณะนี้ค่ะ")
    except Exception as e:
        speak(f"เกิดข้อผิดพลาดในการแปลภาษาค่ะ {e}")