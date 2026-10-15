import ctypes
import os
from config import WAKE_WORDS
from speech import speak, record_and_recognize
from ad_skipper import start_auto_skip_ads, stop_auto_skip_ads
# นำเข้าฟังก์ชันจาก assistant.py ที่คุณจัดกลุ่มไว้
from assistant import find_wake_word, strip_wake_words, interpret, handle_command

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

def main():
    speak("ระบบผู้ช่วยอัจฉริยะพร้อมใช้งานแล้วครับ")
    start_auto_skip_ads()
    try:
        while True:
            command = record_and_recognize()

            if command and find_wake_word(command):
                print(f"🎯 คุณพูดว่า: {command}")
                actual_command = strip_wake_words(command)

                if actual_command:
                    print("🧠 กำลังวิเคราะห์คำสั่ง...")
                    intent_result = interpret(actual_command)
                    print(f"🤖 ผลลัพธ์: {intent_result}")

                    # ส่ง actual_command เข้าไปบันทึกด้วย
                    if handle_command(intent_result, actual_command):
                        break
                else:
                        speak("ครับ มีอะไรให้ช่วยไหมครับ")
                        follow_up = record_and_recognize("พูดคำสั่งได้เลย (ไม่ต้องเรียกชื่อ)...")
                        if follow_up:
                            # เก็บข้อความดิบไว้ก่อนตัดคำ
                            raw_follow_up = strip_wake_words(follow_up)
                            
                            intent_result = interpret(raw_follow_up)
                            print(f"🤖 ผลลัพธ์: {intent_result}")
                            
                            # ส่ง raw_follow_up เข้าไปให้ handle_command บันทึก Log ด้วย
                            if handle_command(intent_result, raw_follow_up):
                                break
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()

if __name__ == "__main__":
    main()