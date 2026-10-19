"""ระบบจัดการโน้ตและบันทึกข้อความแบบต่อเนื่องของราฟาเอล"""
import datetime
import os
import re
from config import BASE_DIR
from speech import record_and_recognize, speak
from Component.widget import start_widget_thread, set_widget_state


NOTE_FILE = os.path.join(BASE_DIR, "my_notes.txt")

# คำสั่งจบ/ยกเลิก ใช้ได้เมื่อ "อยู่ท้ายประโยค" หรือประโยคสั้นๆ เท่านั้น
# ไม่งั้นโน้ตที่มีคำเหล่านี้อยู่ข้างใน (เช่น "ต้องบันทึกการประชุม" "ยกเลิกนัดวันศุกร์") จะถูกตัดหรือทิ้งทั้งประโยค
END_PATTERN = re.compile(r"(บันทึก|พอแค่นี้|เสร็จแล้ว|จัดเก็บ)\s*(?:ให้|ด้วย|เลย|นะ|ค่ะ|คะ|ครับ|หน่อย)*$")
CANCEL_WORDS = ["ยกเลิก", "ไม่เอาแล้ว", "ทิ้งเลย"]
NO_MORE_WORDS = ["ไม่มี", "ไม่เพิ่ม", "ไม่ต้อง", "พอแล้ว", "เสร็จ", "ไม่"]     # เช็กก่อนเสมอ เพราะ "ไม่มี" มีคำว่า "มี" อยู่ข้างใน
MORE_WORDS = ["มี", "ต่อ", "เพิ่ม", "ยัง"]

# def cmd_write_notepad(query):
#     if not query:
#         speak("ต้องการให้บันทึกข้อความว่าอะไรค่ะ")
#         query = strip_phrases(strip_wake_words(record_and_recognize("พูดข้อความ...")), ["บันทึก", "จดจำ", "เขียนว่า"])
#     if not query:
#         speak("ไม่ได้ยินข้อความค่ะ")
#         return
#     if pyperclip is None:
#         speak("ต้องติดตั้งโมดูล pyperclip ก่อนค่ะ")
#         return
#     speak("กำลังบันทึกข้อความลงใน Notepad ค่ะ")
#     os.system("start notepad")
#     wait_for_window("notepad")
#     time.sleep(0.3)
#     paste_text(query)



def interactive_note_session(initial_query=""):
  """เข้าสู่โหมดบันทึกโน้ตแบบต่อเนื่อง ฟังยาวๆ จนกว่าจะสั่งบันทึกโดยไม่พูดแทรกขัดจังหวะ"""
  speak(
      "เข้าสู่โหมดบันทึกโน้ตค่ะ พูดเรื่องที่ต้องการบันทึกยาวๆ"
      " ได้ตามสบายเลยค่ะ"
      " ถ้าพูดจบแล้วให้พูดคำว่า 'บันทึก' หรือ 'เสร็จแล้ว' นะคะ"
  )

  notes_buffer = []
  if initial_query:
    notes_buffer.append(initial_query)

  while True:
    # เปิดฟังยาวๆ โดยไม่มีเสียงพูดตอบกลับระหว่างทางมารบกวน
    set_widget_state("listening")
    speech = record_and_recognize("กำลังฟังโน้ตของคุณ... (พูดต่อได้เลยค่ะ)")

    if not speech:
      # ถ้าเงียบไปนานเกินไป ค่อยถามเช็กเบาๆ ว่าจะบันทึกเลยไหม
      speak("ดูเหมือนท่านจะเงียบไป มีอะไรจะแจ้งเพิ่มไหมคะ")
      confirm_speech = record_and_recognize("รอคำตอบ... (พูด 'มี' หรือ 'ไม่มี')")

      wants_more = (
          bool(confirm_speech)
          and not any(w in confirm_speech for w in NO_MORE_WORDS)
          and any(w in confirm_speech for w in MORE_WORDS)
      )
      if wants_more:
        continue
      break

    compact = re.sub(r"\s+", "", speech)

    # คำสั่งยกเลิก (เฉพาะประโยคสั้นๆ)
    if len(compact) <= 12 and any(w in speech for w in CANCEL_WORDS):
      speak("ยกเลิกการบันทึกโน้ตเรียบร้อยค่ะ")
      return

    # คำสั่งจบ (อยู่ท้ายประโยค) เก็บส่วนที่พูดก่อนหน้าไว้ด้วย
    m = END_PATTERN.search(speech)
    if m:
      before = speech[:m.start()].strip()
      if before:
        notes_buffer.append(before)
      break

    # สะสมข้อความเงียบๆ โดยไม่พูดแทรกขัดจังหวะ
    notes_buffer.append(speech)

  if not notes_buffer:
    speak("ไม่มีข้อมูลสำหรับบันทึกค่ะ")
    return

  full_note = " ".join(notes_buffer)
  timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  try:
    with open(NOTE_FILE, "a", encoding="utf-8") as f:
      f.write(f"\n--- [{timestamp}] ---\n{full_note}\n")
    speak("บันทึกโน้ตลงไฟล์เดิมเรียบร้อยแล้วค่ะท่าน")
    open_notes_file()
  except Exception as e:
    speak(f"บันทึกโน้ตไม่สำเร็จค่ะ {e}")


def open_notes_file(_query=""):
  """เปิดไฟล์โน้ตด้วย Notepad ขึ้นมาแสดงผล"""
  if not os.path.exists(NOTE_FILE):
    speak("ยังไม่มีประวัติการบันทึกโน้ตค่ะ")
    return
  speak("กำลังเปิดไฟล์โน้ตให้ค่ะ")
  os.system(f'start notepad "{NOTE_FILE}"')