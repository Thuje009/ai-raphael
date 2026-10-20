import ctypes
import os
import json
import threading
import time
import sys
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
from Component.ig_bot import start_ig_bot_thread, IG_BUSY


# --- จุดแก้ไข 2: ลบ import _config_data ที่เป็นปัญหาออก ---
# ลบ: from config import _config_data
# ลบ: telegram_token = _config_data.get("telegram_bot_token", "")
# --------------------------------------------------------

# --- จุดแก้ไข 3: ตรวจสอบการ import Component/tele_bot.py ---
try:
    from Component.tele_bot import start_telegram_bot_thread
except ImportError:
    print("⚠️ ไม่พบไฟล์ Component/tele_bot.py กรุณาสร้างไฟล์นี้ก่อนรันโปรแกรม")
    sys.exit(1)
# ------------------------------------------------------------

# --- เพิ่มใหม่: ฟังก์ชันสำหรับโหลด Config จาก config.json โดยตรง ---
def load_config():
    """โหลดข้อมูลจาก config.json โดยตรง"""
    default_config = {
        "assistant_name": "raphael",
        "stt_engine": "groq",
        "telegram_bot_token": ""
    }
    
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ อ่าน config.json ไม่สำเร็จ: {e}")
            return default_config
    else:
        # ถ้าไม่มีไฟล์ ให้สร้าง default ขึ้นมา
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        return default_config
# -------------------------------------------------------------

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
    start_widget_thread()
    set_widget_state("speaking")
    config_data = load_config()
    speak("มีอะไรให้ ราฟาเอล ช่วยคะ")
    start_auto_skip_ads()
    start_reminder_system()
    set_widget_state("hidden")

    # --- โหลดและสั่งรัน Telegram Bot ---
    telegram_token = config_data.get("telegram_bot_token", "")
    
    if telegram_token and telegram_token.strip() != "":
        print("📱 [System] เริ่มต้นระบบ Telegram Bot สแตนด์บายรับคำสั่งจากมือถือแล้วค่ะ")
        start_telegram_bot_thread(telegram_token)
    else:
        print("⚠️ [System] แจ้งเตือน: ไม่พบ Telegram Bot Token หรือยังไม่ได้ใส่ Token จริงใน config.json")
        print("   -> ระบบสั่งงานผ่านมือถือจะไม่ทำงาน")
    
    # เริ่มต้นระบบสแตนด์บายตรวจจับแชท IG
    print("🤖 [System] เริ่มต้นระบบ Instagram Bot สแตนด์บายตรวจจับข้อความแล้วค่ะ")
    start_ig_bot_thread()

    try:
        while True:
            try:
                # ถ้า IG Bot กำลังใช้งานไมค์อยู่ ให้ลูปหลักข้ามการฟังไปก่อน
                if IG_BUSY.is_set():
                    time.sleep(0.5)
                    continue

                # เธรดเช็กเวลาแจ้งเตือน
                for entry in pop_due():
                    handle_due(entry)
                
                # รับคำสั่งเสียงจากผู้ใช้ในลูปหลัก
                command = record_and_recognize()
                set_widget_state("hidden")
                
                if not (command and find_wake_word(command)):
                    continue
 
                print(f"🎯 คุณพูดว่า: {command}")
                actual_command = strip_wake_words(command)
 
                if not actual_command:
                    speak("ครับ มีอะไรให้ช่วยไหมครับ")
                    follow_up = record_and_recognize("พูดคำสั่งได้เลย (ไม่ต้องเรียกชื่อ)...")
                    actual_command = strip_wake_words(follow_up) if follow_up else ""
 
                if actual_command and run_command(actual_command):
                    break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"⚠️ เกิดข้อผิดพลาด: {e}")
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()
        stop_reminder_system()
        
if __name__ == "__main__":
    main()