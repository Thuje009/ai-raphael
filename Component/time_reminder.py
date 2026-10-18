"""ระบบจัดการเวลา วันที่ และรายการแจ้งเตือนของราฟาเอล"""
import datetime
import re
import llm
import reminder
from knowledge import DAYS_TH, MONTHS_TH
from speech import record_and_recognize, speak


def cmd_get_time(_query):
  now = datetime.datetime.now()
  speak(
      f"เวลาปัจจุบันคือ {now.strftime('%H:%M')} น.",
      say=f"ตอนนี้เวลา {now.hour} นาฬิกา {now.minute} นาทีค่ะ",
  )


def cmd_get_date(query):
  try:
    offset = int(query)
  except (TypeError, ValueError):
    offset = 0
  d = datetime.date.today() + datetime.timedelta(days=offset)
  label = {-1: "เมื่อวานนี้", 0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}.get(
      offset, "วันนั้น"
  )
  speak(
      f"{label}เป็น{DAYS_TH[d.weekday()]}ที่ {d.day} {MONTHS_TH[d.month - 1]}"
      f" พ.ศ. {d.year + 543} ค่ะ"
  )


def cmd_check_specific_date(query):
  numbers = re.findall(r"\d+", query)
  if not numbers:
    speak("ไม่พบวันที่ที่ต้องการทราบค่ะ")
    return
  target_day = int(numbers[0])
  now = datetime.datetime.now()
  try:
    target = datetime.date(now.year, now.month, target_day)
  except ValueError:
    speak("เดือนนี้ไม่มีวันที่ตามที่ระบุค่ะ")
    return
  speak(
      f"วันที่ {target_day} {MONTHS_TH[now.month - 1]}"
      f" เป็น{DAYS_TH[target.weekday()]}ค่ะ"
  )


def cmd_set_reminder(query):
  found = reminder.parse_request(query)
  if found is None and llm.llm_available():
    found = llm.parse_reminder(query)
    if found and not found["message"]:
      found["message"] = reminder.clean_message(query, [])
  if found is None:
    speak("ไม่พบเวลาที่ต้องการให้เตือนค่ะ")
    return
  when, message = found["when"], found["message"] or "ตามที่นัดหมาย"
  if when <= datetime.datetime.now():
    speak("เวลานั้นผ่านไปแล้วค่ะ")
    return
  reminder.add_reminder(when, message)
  speak(f"ตั้งเตือน {reminder.spoken_time(when)} เรื่อง {message} เรียบร้อยค่ะ")


def cmd_list_reminders(_query):
  pending = reminder.list_pending()
  if not pending:
    speak("ไม่มีรายการเตือนค้างอยู่ค่ะ")
    return
  speak(f"มีรายการเตือน {len(pending)} รายการค่ะ")
  for r in pending[:5]:
    when = datetime.datetime.strptime(r["time"], reminder.FMT)
    speak(f"{reminder.spoken_time(when)} {r['message']}")


def cmd_cancel_reminders(query, confirm_fn):
  pending = reminder.list_pending()
  if not pending:
    speak("ไม่มีรายการเตือนให้ยกเลิกค่ะ")
    return
  keyword = strip_phrases(
      query,
      [
          "ยกเลิกการเตือน",
          "ยกเลิกเตือน",
          "ลบการเตือน",
          "ลบเตือน",
          "ทั้งหมด",
          "เรื่อง",
          "เกี่ยวกับ",
      ],
  ).strip()
  if keyword:
    removed = reminder.cancel(keyword)
    speak(
        f"ยกเลิกรายการเตือนเกี่ยวกับ {keyword} จำนวน {removed} รายการแล้วค่ะ"
        if removed
        else f"ไม่พบรายการเตือนเกี่ยวกับ {keyword} ค่ะ"
    )
  elif len(pending) == 1 or confirm_fn(
      f"มีรายการเตือน {len(pending)} รายการ ยืนยันยกเลิกทั้งหมดไหมคะ"
  ):
    speak(f"ยกเลิกรายการเตือนทั้งหมด {reminder.cancel()} รายการแล้วค่ะ")
  else:
    speak("ยกเลิกค่ะ")


def strip_phrases(text, phrases):
  for p in phrases:
    text = text.replace(p, "")
  return text.strip()