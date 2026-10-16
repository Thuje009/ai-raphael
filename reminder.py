"""
ระบบแจ้งเตือนของราฟาเอล

หลักการสำคัญ: เธรดเบื้องหลัง "เช็กเวลาอย่างเดียว" เมื่อถึงเวลาจะใส่รายการเข้าคิว
ส่วนการพูดและฟังคำตอบ (handle_due) ต้องทำที่เธรดหลักเท่านั้น เพราะไมค์และลำโพง
ใช้พร้อมกันสองเธรดไม่ได้ (ไฟล์ temp_audio.wav และ MCI alias จะชนกัน)
"""
import json
import os
import queue
import re
import threading
import uuid
from datetime import date, datetime, time as dtime, timedelta

from config import (BASE_DIR, REMINDER_CHECK_SEC, REMINDER_MAX_REPEAT, REMINDER_REPEAT_GAP_SEC,
                    REMINDER_SNOOZE_MIN, REMINDER_LATE_MIN, REMINDER_KEEP_DAYS)
from knowledge import MONTHS_TH
from speech import speak, record_and_recognize

REMINDER_FILE = os.path.join(BASE_DIR, "reminders.json")
FMT = "%Y-%m-%d %H:%M"

_lock = threading.RLock()          # กันอ่าน-เขียนไฟล์ชนกันระหว่างเธรดเช็กเวลากับเธรดหลัก
due_queue = queue.Queue()
reminder_stop = threading.Event()
reminder_thread = None


# =====================================================================
# ไฟล์เก็บข้อมูล (เรียกใช้ภายใต้ _lock เสมอ)
# =====================================================================
def _load():
    if not os.path.exists(REMINDER_FILE):
        return []
    try:
        with open(REMINDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("รูปแบบไฟล์ไม่ใช่ list")
    except Exception as e:
        # ไฟล์เสีย: เก็บไว้เป็น .bad แทนการเขียนทับจนข้อมูลหาย
        print(f"⚠️ อ่าน reminders.json ไม่ได้ ({e}) ย้ายไฟล์เดิมไปเป็น .bad")
        try:
            os.replace(REMINDER_FILE, REMINDER_FILE + ".bad")
        except OSError:
            pass
        return []
    items = [r for r in data if isinstance(r, dict) and "time" in r]
    for r in items:
        r.setdefault("id", uuid.uuid4().hex[:8])
        r.setdefault("notified", False)
    return items


def _save(items):
    tmp = REMINDER_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, REMINDER_FILE)          # เขียนแบบ atomic ไฟล์ไม่เสียถ้าโปรแกรมดับกลางคัน
    except OSError as e:
        print(f"⚠️ บันทึกไฟล์เตือนไม่สำเร็จ: {e}")


def _when(entry):
    try:
        return datetime.strptime(entry.get("time", ""), FMT)
    except ValueError:
        return None


def add_reminder(when, message):
    """when เป็น datetime คืน entry ที่บันทึกแล้ว (ไม่พูดอะไร ให้ผู้เรียกเป็นคนพูดเอง)"""
    entry = {"id": uuid.uuid4().hex[:8], "time": when.strftime(FMT),
             "message": message, "notified": False, "status": "pending"}
    with _lock:
        items = _load()
        items.append(entry)
        _save(items)
    print(f"⏰ ตั้งเตือนสำเร็จ: {entry['time']} -> {message}")
    return entry


def list_pending():
    with _lock:
        pending = [r for r in _load() if not r.get("notified")]
    return sorted(pending, key=lambda r: r["time"])


def cancel(keyword=None):
    """ยกเลิกรายการที่ยังไม่ถึงเวลา: ถ้ามี keyword ยกเลิกเฉพาะที่ข้อความตรง ไม่มีก็ทั้งหมด คืนจำนวนที่ยกเลิก"""
    with _lock:
        items = _load()
        keep, removed = [], 0
        for r in items:
            hit = not r.get("notified") and (not keyword or keyword in r.get("message", ""))
            if hit:
                removed += 1
            else:
                keep.append(r)
        if removed:
            _save(keep)
    return removed


# =====================================================================
# แปลงคำพูดเป็นเวลา
#   รองรับ: 18:00 | 6 โมงเย็น | บ่าย 3 โมงครึ่ง | ตี 5 | 2 ทุ่ม | เที่ยง | เที่ยงคืน
#           อีก 10 นาที | อีก 2 ชั่วโมง | อีกครึ่งชั่วโมง | พรุ่งนี้ / มะรืนนี้ / วันนี้
#   คำที่กำกวม (เช่น "6 โมง" ไม่บอกเช้าเย็น) จะเลือก "ครั้งถัดไปที่จะมาถึง" แล้วอ่านเวลากลับให้ฟัง
# =====================================================================
_DAY_WORDS = (("มะรืนนี้", 2), ("มะรืน", 2), ("พรุ่งนี้", 1), ("วันนี้", 0))


def _pm(n):
    return n + 12 if n < 12 else n


def _hours_from_mong(m):
    n, period = int(m.group(1)), m.group(2)
    if period == "เช้า":
        return [n]
    if period in ("เย็น", "ค่ำ"):
        return [_pm(n)]
    if n == 12:
        return [12]
    if 1 <= n <= 5:
        return [n + 12]          # "3 โมง" เฉยๆ มักหมายถึงบ่าย 3 โมง
    return [n, n + 12]


_HOUR_RULES = [
    (r"เที่ยงคืน", lambda m: [0]),
    (r"เที่ยง", lambda m: [12]),
    (r"บ่ายโมง", lambda m: [13]),
    (r"บ่าย\s*(\d{1,2})\s*(?:โมง)?", lambda m: [_pm(int(m.group(1)))]),
    (r"ตี\s*(\d{1,2})", lambda m: [int(m.group(1))]),
    (r"(\d{1,2})\s*ทุ่ม", lambda m: [(int(m.group(1)) + 18) % 24]),
    (r"(\d{1,2})\s*โมง\s*(เช้า|เย็น|ค่ำ)?", _hours_from_mong),
    (r"(\d{1,2})\s*นาฬิกา", lambda m: [int(m.group(1)) % 24]),
]


def parse_when(text, now=None):
    """คืน (datetime, [ข้อความส่วนที่เป็นเวลา]) หรือ None ถ้าหาเวลาไม่เจอ"""
    now = (now or datetime.now()).replace(second=0, microsecond=0)

    # --- 1) แบบสัมพัทธ์ ---
    m = re.search(r"อีก\s*(ครึ่งชั่วโมง|(\d+)?\s*(ชั่วโมง|นาที|วัน)(ครึ่ง)?)", text)
    if m:
        if m.group(1) == "ครึ่งชั่วโมง":
            delta = timedelta(minutes=30)
        else:
            n = int(m.group(2)) if m.group(2) else 1
            unit = m.group(3)
            delta = {"ชั่วโมง": timedelta(hours=n), "นาที": timedelta(minutes=n),
                     "วัน": timedelta(days=n)}[unit]
            if m.group(4):
                delta += {"ชั่วโมง": timedelta(minutes=30), "วัน": timedelta(hours=12)}.get(unit, timedelta())
        return now + delta, [m.group(0)]

    spans = []

    # --- 2) วัน ---
    day_offset = None
    for word, off in _DAY_WORDS:
        if word in text:
            day_offset = off
            spans.append(word)
            break

    # --- 3) เวลา ---
    hours, minute, colon_format = None, 0, False
    m = re.search(r"(\d{1,2})[:.](\d{2})(?:\s*น\.|\s*นาฬิกา)?", text)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if h > 24 or minute > 59:
            return None
        colon_format = True
        explicit = m.group(1).startswith("0") or h == 0 or h >= 12     # 09:00, 18:00, 12:30 ถือว่าชัดเจน
        hours = [h % 24] if explicit else [h, h + 12]
        spans.append(m.group(0))
    else:
        for pattern, fn in _HOUR_RULES:
            m = re.search(pattern, text)
            if m:
                hours = fn(m)
                spans.append(m.group(0))
                break
    if hours is None or any(h < 0 or h > 23 for h in hours):
        return None

    if not colon_format:
        if "ครึ่ง" in text:
            minute = 30
            spans.append("ครึ่ง")
        else:
            mm = re.search(r"(\d{1,2})\s*นาที", text)
            if mm and int(mm.group(1)) < 60:
                minute = int(mm.group(1))
                spans.append(mm.group(0))

    base = now.date() + timedelta(days=day_offset or 0)
    cands = []
    for h in hours:
        cands.append(datetime.combine(base, dtime(h, minute)))
        if day_offset is None:
            cands.append(datetime.combine(base + timedelta(days=1), dtime(h, minute)))
    future = [c for c in cands if c > now]
    return (min(future) if future else min(cands)), spans


def clean_message(text, spans):
    """ตัดคำสั่งและส่วนที่เป็นเวลาออก เหลือแต่สิ่งที่จะให้เตือน"""
    for sp in sorted(set(spans), key=len, reverse=True):
        text = text.replace(sp, " ")
    text = re.sub(r"ตั้งเตือนความจำ|ตั้งเตือน|แจ้งเตือน|เตือนความจำ|เตือน", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:(?:ช่วย|ขอ)\s+)?(?:(?:ให้ฉัน|ให้ผม|ฉัน|ผม|ว่า|ด้วย|หน่อย|นะ)\s*)*", "", text)
    text = re.sub(r"(?:\s*(?:ด้วย|นะ|หน่อย|ครับ|ค่ะ|คะ))+$", "", text)
    return text.strip()


def parse_request(text, now=None):
    """คืน {"when": datetime, "message": str} หรือ None ถ้าหาเวลาไม่เจอ"""
    found = parse_when(text, now)
    if not found:
        return None
    when, spans = found
    return {"when": when, "message": clean_message(text, spans)}


def spoken_time(dt):
    """ข้อความสำหรับพูด เช่น 'วันนี้ เวลา 18 นาฬิกา 30 นาที'"""
    days = (dt.date() - date.today()).days
    day = {0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}.get(days, f"วันที่ {dt.day} {MONTHS_TH[dt.month - 1]}")
    t = f"{dt.hour} นาฬิกา" + (f" {dt.minute} นาที" if dt.minute else "")
    return f"{day} เวลา {t}"


# =====================================================================
# เธรดเช็กเวลา (ไม่พูด ไม่ใช้ไมค์)
# =====================================================================
def reminder_loop():
    print("⏰ [Reminder System] เริ่มระบบตรวจสอบเวลาแจ้งเตือนแล้ว")
    while not reminder_stop.is_set():
        try:
            now = datetime.now()
            due = []
            with _lock:
                items = _load()
                changed = False
                for r in items:
                    if r.get("notified"):
                        continue
                    when = _when(r)
                    if when is None:
                        r["notified"], r["status"], changed = True, "invalid", True
                    elif when <= now:
                        r["notified"], r["status"], changed = True, "fired", True
                        due.append({**r, "late_min": int((now - when).total_seconds() // 60)})

                cutoff = now - timedelta(days=REMINDER_KEEP_DAYS)       # ล้างรายการเก่าไม่ให้ไฟล์โตไม่รู้จบ
                kept = [r for r in items if not (r.get("notified") and (_when(r) or now) < cutoff)]
                if changed or len(kept) != len(items):
                    _save(kept)
            for d in due:
                due_queue.put(d)
        except Exception as e:
            print(f"⚠️ Reminder Error: {e}")
        reminder_stop.wait(REMINDER_CHECK_SEC)


def start_reminder_system():
    global reminder_thread
    if reminder_thread and reminder_thread.is_alive():
        return
    reminder_stop.clear()
    reminder_thread = threading.Thread(target=reminder_loop, daemon=True, name="Raphael-Reminder")
    reminder_thread.start()


def stop_reminder_system():
    reminder_stop.set()


def pop_due():
    """ดึงรายการที่ถึงเวลาแล้วออกจากคิว (เรียกจากเธรดหลัก)"""
    items = []
    while True:
        try:
            items.append(due_queue.get_nowait())
        except queue.Empty:
            return items


# =====================================================================
# แจ้งเตือน + รอคำตอบ (เรียกจากเธรดหลักเท่านั้น)
# =====================================================================
DENY_WORDS = ["ไม่รับทราบ", "ไม่ตกลง", "ไม่เอา", "ไม่ต้อง"]
ACK_WORDS = ["รับทราบ", "ทราบแล้ว", "โอเค", "ตกลง", "เรียบร้อย", "ok"]


def classify_reply(reply):
    """คืน 'deny' | 'snooze' | 'ack' | None
    ต้องเช็กคำปฏิเสธก่อนเสมอ เพราะ "ไม่รับทราบ" มีคำว่า "รับทราบ" อยู่ข้างใน"""
    r = (reply or "").lower()
    if any(w in r for w in DENY_WORDS):
        return "deny"
    if "เลื่อน" in r or "ขออีก" in r or ("อีก" in r and "นาที" in r):
        return "snooze"
    if any(w in r for w in ACK_WORDS):
        return "ack"
    return None


def handle_due(entry):
    message = entry["message"]
    late = entry.get("late_min", 0)
    prefix = f"เลยเวลามาแล้ว {late} นาที " if late >= REMINDER_LATE_MIN else ""

    for attempt in range(REMINDER_MAX_REPEAT):
        if attempt == 0:
            speak(f"รายงาน {prefix}ถึงเวลา {message} ที่ท่านให้เตือนแล้วครับ กรุณารับทราบด้วยครับ")
        else:
            speak(f"เตือนซ้ำครับ ถึงเวลา {message} แล้ว กรุณารับทราบด้วยครับ")

        reply = record_and_recognize("พูด 'รับทราบ' หรือ 'เลื่อน 10 นาที' หรือ 'ไม่รับทราบ'...")
        kind = classify_reply(reply)

        if kind == "ack":
            speak("บันทึกการรับทราบเรียบร้อยครับ")
            return "ack"
        if kind == "deny":
            speak("รายงาน ราฟาเอลทำหน้าที่แจ้งเตือนแล้ว ท่านไม่รับทราบเองไม่ใช่ความผิดของราฟาเอล แล้วขอบคุณค่ะ")
            return "deny"
        if kind == "snooze":
            m = re.search(r"(\d+)\s*นาที", reply)
            minutes = int(m.group(1)) if m else REMINDER_SNOOZE_MIN
            add_reminder(datetime.now() + timedelta(minutes=minutes), message)
            speak(f"เลื่อนไปอีก {minutes} นาทีครับ")
            return "snooze"

        if attempt < REMINDER_MAX_REPEAT - 1:
            speak("ยังไม่ได้คำตอบที่ชัดเจน ขอเตือนซ้ำอีกรอบนะครับ")
            if reminder_stop.wait(REMINDER_REPEAT_GAP_SEC):
                return "stopped"

    speak("ยังไม่ได้รับคำตอบ ขอบันทึกไว้ว่าท่านพลาดการแจ้งเตือนนี้นะครับ")
    return "missed"