import ctypes
import Component.translator


# ต้องตั้ง DPI awareness ก่อน import อย่างอื่น ไม่เช่นนั้นพิกัดการจับภาพกับพิกัดเมาส์จะไม่ตรงกัน
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from speech import speak, record_and_recognize
from ad_skipper import start_auto_skip_ads, stop_auto_skip_ads
from reminder import start_reminder_system, stop_reminder_system, pop_due, handle_due
from assistant import find_wake_word, strip_wake_words, interpret, handle_command
from Component.widget import start_widget_thread, set_widget_state
from Component.setup_wizard import run_setup_wizard_if_needed
from config import get_assistant_name

def run_command(text):
    """วิเคราะห์และสั่งงาน คืน True ถ้าผู้ใช้สั่งปิดระบบ"""
    print("🧠 กำลังวิเคราะห์คำสั่ง...")
    
    # กำลังวิเคราะห์/คิดคำตอบ -> เปลี่ยน Widget เป็นสีม่วง (thinking)
    set_widget_state("thinking")
    
    intent_result = interpret(text)
    print(f"🤖 ผลลัพธ์: {intent_result}")
    
    intent = intent_result.get('intent') if isinstance(intent_result, dict) else ""
    
    if intent == 'translate' or 'แปล' in text:
        Component.translator.translate_selected_text()
        set_widget_state("hidden") # ทำงานเสร็จ ซ่อน Widget
        return False
        
    res = handle_command(intent_result, text)
    set_widget_state("hidden") # ทำงานเสร็จ ซ่อน Widget
    return res

def main():
    run_setup_wizard_if_needed()
    start_widget_thread()
    set_widget_state("speaking")
    assistant_name = get_assistant_name()
    speak(f"มีอะไรให้ {assistant_name} ช่วยคะ")
    start_auto_skip_ads()
    start_reminder_system()
    set_widget_state("hidden")
    try:
        while True:
            try:
                # เธรดเช็กเวลาแค่ส่งรายการที่ถึงเวลามาใส่คิว การพูดและฟังคำตอบทำที่นี่ (เธรดหลัก)
                # เพื่อไม่ให้แย่งไมค์/ลำโพงกับลูปรอฟังคำสั่ง (อาจหน่วงได้ไม่เกินราว 6 วินาที)
                for entry in pop_due():
                    handle_due(entry)
                command = record_and_recognize()
                set_widget_state("hidden")
                
                # ตรวจสอบคำปลุกทุกครั้ง ถ้าไม่มีคำปลุก ดีดกลับไปรอดักฟังใหม่ทันที
                if not (command and find_wake_word(command)):
                    continue
 
                print(f"🎯 คุณพูดว่า: {command}")
                actual_command = strip_wake_words(command)
 
                # ถ้าเรียกชื่อเปล่าๆ ไม่มีคำสั่งตามหลัง ให้ทักทายสั้นๆ แล้วกลับไปรอดักฟังใหม่
                if not actual_command:
                    speak("คะ ว่ายังไงคะ")
                    continue
 
                if actual_command and run_command(actual_command):
                    break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # ข้อผิดพลาดจากคำสั่งเดียวไม่ควรทำให้ผู้ช่วยดับทั้งโปรแกรม
                print(f"⚠️ เกิดข้อผิดพลาด: {e}")
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()
        stop_reminder_system()

if __name__ == "__main__":
    main()