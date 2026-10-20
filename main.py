import ctypes
import json
import os
import sys
import time
import traceback

# ต้องตั้ง DPI awareness ก่อน import อย่างอื่นที่แตะหน้าจอ/เมาส์ (mss, pyautogui, ad_skipper ฯลฯ)
# ไม่เช่นนั้นพิกัดการจับภาพกับพิกัดเมาส์จะไม่ตรงกัน
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

# Telegram เป็นส่วนเสริม: ถ้าไม่มีไฟล์ก็ข้ามไป ไม่ให้ทั้งโปรแกรมล้ม
try:
    from Component.tele_bot import start_telegram_bot_thread
except ImportError:
    start_telegram_bot_thread = None
    print("⚠️ ไม่พบ Component/tele_bot.py ข้ามระบบ Telegram")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")   # ไม่ผูกกับโฟลเดอร์ที่สั่งรัน (สำคัญตอนรันจาก Startup)

DEFAULT_CONFIG = {
    "assistant_name": "raphael",
    "stt_engine": "groq",
    "telegram_bot_token": "",
}


def load_config():
    """โหลด config.json (เติมค่า default ให้คีย์ที่ขาด)"""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except Exception as e:
        print(f"⚠️ อ่าน config.json ไม่สำเร็จ: {e}")
        return dict(DEFAULT_CONFIG)


def run_command(text):
    """วิเคราะห์และสั่งงาน คืน True ถ้าผู้ใช้สั่งปิดระบบ"""
    print("🧠 กำลังวิเคราะห์คำสั่ง...")
    set_widget_state("thinking")        # สีม่วง
    try:
        intent_result = interpret(text)
        print(f"🤖 ผลลัพธ์: {intent_result}")
        # การแปลภาษาจัดการผ่าน intent "translate_text" ใน COMMANDS แล้ว
        return handle_command(intent_result, text)
    finally:
        set_widget_state("hidden")      # error กลางทางก็ไม่ค้างสีม่วง


def start_telegram(config_data):
    token = (config_data.get("telegram_bot_token") or "").strip()
    if start_telegram_bot_thread and token:
        print("📱 [System] เริ่มระบบ Telegram Bot สแตนด์บายรับคำสั่งจากมือถือแล้วค่ะ")
        start_telegram_bot_thread(token)
    else:
        print("⚠️ [System] ไม่เริ่ม Telegram Bot (ไม่มี token ใน config.json หรือไม่มีไฟล์ tele_bot.py)")


def main():
    start_widget_thread()
    set_widget_state("speaking")
    config_data = load_config()
    speak("มีอะไรให้ ราฟาเอล ช่วยคะ")
    start_auto_skip_ads()
    start_reminder_system()
    set_widget_state("hidden")

    start_telegram(config_data)

    print("🤖 [System] เริ่มระบบ Instagram Bot สแตนด์บายตรวจจับข้อความแล้วค่ะ")
    start_ig_bot_thread()

    try:
        while True:
            try:
                # เช็กการเตือนก่อนเสมอ (เดิมอยู่หลัง IG_BUSY ทำให้เตือนช้าตอน IG Bot ใช้ไมค์)
                for entry in pop_due():
                    handle_due(entry)

                # ถ้า IG Bot กำลังใช้ไมค์อยู่ ให้ข้ามการฟังไปก่อน
                if IG_BUSY.is_set():
                    time.sleep(0.5)
                    continue

                command = record_and_recognize()
                set_widget_state("hidden")

                if not (command and find_wake_word(command)):
                    continue

                print(f"🎯 คุณพูดว่า: {command}")
                actual_command = strip_wake_words(command)

                if not actual_command:
                    speak("ค่ะ มีอะไรให้ช่วยไหมคะ")
                    follow_up = record_and_recognize("พูดคำสั่งได้เลย (ไม่ต้องเรียกชื่อ)...")
                    actual_command = strip_wake_words(follow_up) if follow_up else ""

                if actual_command and run_command(actual_command):
                    break
            except KeyboardInterrupt:
                raise
            except Exception:
                traceback.print_exc()       # เห็นบรรทัดที่พังจริง ไม่ใช่แค่ข้อความสั้น ๆ
                time.sleep(1)               # กันลูปรัวเมื่อ error ซ้ำ ๆ (เช่น ไมค์หลุด)
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()
        stop_reminder_system()


if __name__ == "__main__":
    main()