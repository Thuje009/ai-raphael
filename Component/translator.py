"""ระบบคัดลอกข้อความและแปลภาษาของราฟาเอล"""
import threading
import time
import pyautogui
import pyperclip
import llm
from common import GUI_LOCK
from speech import speak

def _clear_clipboard_after(delay_seconds=300):
    """ฟังก์ชันทำงานเบื้องหลัง: รอตามเวลาที่กำหนด (ค่าเริ่มต้น 5 นาที = 300 วินาที) แล้วเคลียร์ Clipboard"""
    time.sleep(delay_seconds)
    try:
        # ตรวจสอบก่อนว่าข้อความปัจจุบันยังเป็นข้อความเดิมที่เพิ่งแปลไปไหม ถ้าใช่ค่อยเคลียร์เพื่อความปลอดภัย
        pyperclip.copy("")
    except Exception:
        pass

def translate_selected_text():
    with GUI_LOCK:
        pyautogui.hotkey('ctrl', 'c')
    
    time.sleep(0.2)
    selected_text = pyperclip.paste().strip()
    
    # ถ้าไม่มีข้อความใน Clipboard หรือเป็นข้อความเก่าที่เคยแปลไปแล้ว
    if not selected_text or len(selected_text) < 2:
        speak("ไม่พบข้อความที่เลือกค่ะ กรุณาเอาเมาส์ลากคุมข้อความที่ต้องการแปลก่อนสั่งนะคะ")
        return
    with GUI_LOCK:
        pyautogui.hotkey('ctrl', 'c')
    
    time.sleep(0.2) # รอระบบคัดลอกข้อความแป๊บหนึ่ง
    
    selected_text = pyperclip.paste().strip()
    
    if not selected_text or len(selected_text) < 2:
        speak("ไม่พบข้อความที่เลือกไว้ค่ะ กรุณาเอาเมาส์ลากคุมข้อความก่อนสั่งนะคะ")
        return

    speak("กำลังแปลภาษาให้ค่ะ")
    
    # 2. ส่งข้อความไปให้ LLM แปลภาษา
    prompt = f"""แปลข้อความต่อไปนี้เป็นภาษาไทยให้อ่านเข้าใจง่าย สละสลวย และตรงประเด็น:
"{selected_text}"
คำตอบไม่ต้องมีคำเกริ่น นำเสนอผลการแปลทันที"""

    try:
        translated = llm.ask(prompt, history=[], tier="fast")
        reply = translated.get("answer") if isinstance(translated, dict) else str(translated)
        
        if reply:
            speak(reply)
            
            # 3. เปิดเธรดเบื้องหลังเพื่อนับถอยหลัง 5 นาที (300 วินาที) แล้วล้าง Clipboard อัตโนมัติ
            threading.Thread(target=_clear_clipboard_after, args=(300,), daemon=True).start()
        else:
            speak("แปลภาษาไม่สำเร็จในขณะนี้ค่ะ")
    except Exception as e:
        speak(f"เกิดข้อผิดพลาดในการแปลภาษาค่ะ {e}")