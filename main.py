import ctypes

# ต้องตั้ง DPI awareness ก่อน import อย่างอื่น ไม่เช่นนั้นพิกัดการจับภาพกับพิกัดเมาส์จะไม่ตรงกัน
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from speech import speak, record_and_recognize
from ad_skipper import start_auto_skip_ads, stop_auto_skip_ads
from reminder import start_reminder_system, stop_reminder_system, pop_due, handle_due
from assistant import find_wake_word, strip_wake_words, interpret, handle_command


def run_command(text):
    """วิเคราะห์และสั่งงาน คืน True ถ้าผู้ใช้สั่งปิดระบบ"""
    print("🧠 กำลังวิเคราะห์คำสั่ง...")
    intent_result = interpret(text)
    print(f"🤖 ผลลัพธ์: {intent_result}")
    return handle_command(intent_result, text)


def main():
    speak("มีอะไรให้ ราฟาเอล ช่วยคะ")
    start_auto_skip_ads()
    start_reminder_system()
    try:
        while True:
            try:
                # เธรดเช็กเวลาแค่ส่งรายการที่ถึงเวลามาใส่คิว การพูดและฟังคำตอบทำที่นี่ (เธรดหลัก)
                # เพื่อไม่ให้แย่งไมค์/ลำโพงกับลูปรอฟังคำสั่ง (อาจหน่วงได้ไม่เกินราว 6 วินาที)
                for entry in pop_due():
                    handle_due(entry)
 
                command = record_and_recognize()
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
                # ข้อผิดพลาดจากคำสั่งเดียวไม่ควรทำให้ผู้ช่วยดับทั้งโปรแกรม
                print(f"⚠️ เกิดข้อผิดพลาด: {e}")
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()
        stop_reminder_system()


if __name__ == "__main__":
    main()