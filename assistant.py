import datetime
import os
import re
import time

import pyautogui
import pygetwindow as gw
from yt_dlp import YoutubeDL

try:
    import pyperclip      # pip install pyperclip (จำเป็นสำหรับพิมพ์ข้อความภาษาไทย)
except ImportError:
    pyperclip = None

import knowledge
import llm
import reminder
from common import GUI_LOCK
from config import BASE_DIR, WAKE_WORDS
from knowledge import DAYS_TH, MONTHS_TH
from logger import log_unknown_command
from speech import speak, record_and_recognize

music = {"queue": [], "index": -1}

UNKNOWN = {"intent": "unknown", "query": ""}

# =====================================================================
# Text & Wake Word Helpers
# =====================================================================
def has_close(text):
    return re.search(r"(?<!เ)ปิด", text) is not None

def has_open(text):
    return "เปิด" in text

def has_any(text, words):
    return any(w in text for w in words)

def find_wake_word(text):
    return next((w for w in sorted(WAKE_WORDS, key=len, reverse=True) if w in text), None)

def strip_wake_words(text):
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        text = text.replace(w, "")
    return text.strip()

def strip_phrases(text, phrases):
    for p in phrases:
        text = text.replace(p, "")
    return text.strip()

# =====================================================================
# YouTube / Music Handlers
# =====================================================================
def search_videos(query, n=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    # ผลค้นหาอาจมีช่อง/เพลย์ลิสต์ปนมา (id ยาวกว่า 11 ตัว) ซึ่งเปิดเป็นวิดีโอไม่ได้ จึงกรองทิ้ง
    return [
        (e.get("title", "ไม่ทราบชื่อ"), f"https://www.youtube.com/watch?v={e['id']}")
        for e in (info.get("entries") or [])
        if e and len(str(e.get("id", ""))) == 11
    ]

BROWSER_NAMES = ("chrome", "edge", "firefox", "brave", "opera")

def find_youtube_windows():
    return [w for w in gw.getAllWindows()
            if w.title and "youtube" in w.title.lower()
            and any(b in w.title.lower() for b in BROWSER_NAMES)]

def active_window_info():
    try:
        w = gw.getActiveWindow()
        if w and w.width > 0:
            return (w.left, w.top, w.left + w.width, w.top + w.height), (w.title or "")
    except Exception:
        pass
    return None, ""

def focus_youtube_window():
    for w in find_youtube_windows():
        try:
            if w.isMinimized:
                w.restore()
            try:
                w.activate()
            except Exception:
                pyautogui.press("alt")
                w.activate()
        except Exception:
            pass
        time.sleep(0.5)
        _, title = active_window_info()
        if "youtube" in title.lower():
            return True
    return False

def open_url(url):
    print(f"🔗 {url}")
    with GUI_LOCK:
        if pyperclip is None:
            print("⚠️ ยังไม่ได้ติดตั้ง pyperclip (pip install pyperclip) จึงเปิดเป็นแท็บใหม่แทน")
        elif focus_youtube_window():
            # ใช้วางแทนพิมพ์: ถ้าคีย์บอร์ดอยู่ภาษาไทย การพิมพ์ URL จะกลายเป็นตัวอักษรไทย
            pyperclip.copy(url)
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")
            return
        os.system(f'start chrome "{url}"')

def play_index(i):
    title, url = music["queue"][i]
    music["index"] = i
    print(f"🎶 ชื่อเพลง: {title}")
    speak("กำลังเล่นเพลงให้ครับ")
    open_url(url)

def play_new_query(query):
    speak(f"กำลังค้นหาเพลง {query} ครับ")
    try:
        results = search_videos(query)
    except Exception as e:
        print(f"❌ ค้นหาไม่สำเร็จ: {e}")
        speak("ค้นหาเพลงไม่สำเร็จครับ")
        return
    if not results:
        speak("ไม่พบเพลงที่ค้นหาครับ")
        return
    music["queue"] = results
    play_index(0)

def play_next():
    if not music["queue"]:
        speak("ยังไม่มีคิวเพลงครับ ลองสั่งเปิดเพลงก่อนนะครับ")
    elif music["index"] + 1 >= len(music["queue"]):
        speak("หมดคิวเพลงแล้วครับ ลองค้นหาเพลงใหม่ได้เลย")
    else:
        play_index(music["index"] + 1)

def play_prev():
    if not music["queue"]:
        speak("ยังไม่มีคิวเพลงครับ")
    elif music["index"] <= 0:
        speak("นี่คือเพลงแรกในคิวแล้วครับ")
    else:
        play_index(music["index"] - 1)

# =====================================================================
# Intent Interpretation
#   1) จับคำพื้นฐาน (เร็ว ไม่ใช้เน็ต)
#   2) knowledge: กฎตายตัว -> cache -> ไฟล์ -> Wikipedia
#   3) LLM (Groq -> Gemini) เรียกรอบเดียวได้ทั้งคำสั่งและคำตอบ
# =====================================================================
def music_query(text):
    """ตัดคำสั่งออก เหลือแต่ชื่อเพลง เช่น 'ช่วยเปิดเพลงเก่าๆ หน่อย' -> 'เก่าๆ'"""
    q = strip_phrases(text, ["หาเพลง", "เปิดเพลง", "ขอเพลง", "ให้ฟังหน่อย", "ให้หน่อย", "หน่อย"])
    return re.sub(r"^(ช่วย|ขอ)", "", q).strip()

def interpret_basic(text):
    opening, closing = has_open(text), has_close(text)

    def result(intent, query=""):
        return {"intent": intent, "query": query}

    def toggle(base):
        return result(f"close_{base}" if closing and not opening else f"open_{base}")

    # --- ยกเลิกปิดเครื่อง ต้องมาก่อน เพราะมีคำว่า "ปิดเครื่อง" อยู่ข้างใน ---
    if has_any(text, ["ยกเลิกปิดเครื่อง", "ยกเลิกการปิดเครื่อง", "ยกเลิกรีสตาร์ท", "ยกเลิกการรีสตาร์ท"]):
        return result("cancel_shutdown")

    # --- ระบบแจ้งเตือน (ต้องมาก่อนคำสั่งอื่น ไม่งั้น "เตือน 6 โมง ปิดเครื่อง" จะไปสั่งปิดเครื่องจริง) ---
    if has_any(text, ["ยกเลิกเตือน", "ยกเลิกการเตือน", "ลบเตือน", "ลบการเตือน"]):
        return result("cancel_reminders", text)
    if has_any(text, ["มีเตือนอะไร", "เตือนอะไรบ้าง", "รายการเตือน", "ดูการเตือน", "ดูเตือน", "เตือนอะไรไว้"]):
        return result("list_reminders")
    if re.search(r"(?<!คำ)เตือน(?!ภัย)", text):
        return result("set_reminder", text)

    # --- โน้ต ---
    if has_any(text, ["บันทึกลงไฟล์", "บันทึกใส่ไฟล์", "จดลงไฟล์", "สร้างโน้ต"]):
        query = strip_phrases(text, ["บันทึกลงไฟล์", "บันทึกใส่ไฟล์", "จดลงไฟล์", "สร้างโน้ต",
                                     "ให้หน่อย", "หน่อย"])
        return result("save_note", query)
    if has_any(text, ["บันทึกข้อความ", "จดโน้ต", "เขียนโน้ต", "โน้ตไว้ว่า"]):
        query = strip_phrases(text, ["บันทึกข้อความ", "จดโน้ต", "เขียนโน้ต", "โน้ตไว้ว่า",
                                     "ให้หน่อย", "หน่อย"])
        return result("write_notepad", query)

    # --- วันที่ (ต้องแยก "มีตัวเลข" ออกจาก "ไม่มีตัวเลข" ไม่งั้น "วันนี้วันอะไร" จะถูกจับผิด) ---
    if re.search(r"\d", text) and has_any(text, ["วันอะไร", "เป็นวัน"]):
        return result("check_specific_date", text)
    if has_any(text, ["วันนี้วันอะไร", "วันอะไรแล้ว", "วันที่เท่าไร", "วันที่เท่าไหร่",
                      "วันนี้วันที่", "พรุ่งนี้วันอะไร", "เมื่อวานวันอะไร", "มะรืนวันอะไร"]):
        offset = 1 if "พรุ่งนี้" in text else -1 if "เมื่อวาน" in text else 2 if "มะรืน" in text else 0
        return result("get_date", str(offset))

    # --- เปิดเพลง (ขึ้นต้นประโยค) ต้องมาก่อนคำสั่งระบบ กันชื่อเพลงที่บังเอิญมีคำสั่งปนอยู่ ---
    if re.match(r"^\s*(?:ช่วย)?(?:เปิด|หา|ขอ)เพลง(?!ต่อไป|ถัดไป|ก่อนหน้า|ที่แล้ว)", text):
        return result("play_music", music_query(text))

    # --- ระบบ ---
    if has_any(text, ["ปิดเครื่อง", "ดับเครื่อง", "shutdown"]):
        return result("shutdown_pc")
    if has_any(text, ["รีสตาร์ท", "รีเครื่อง", "restart"]):
        return result("restart_pc")
    if has_any(text, ["พักเครื่อง", "สลีป", "sleep pc"]):
        return result("sleep_pc")
    if has_any(text, ["หยุดการทำงาน", "ออกจากโปรแกรม"]) or re.search(r"(?<!เ)ปิดระบบ", text):
        return result("exit_system")
    if re.search(r"(?<!เ)ปิด(หน้าต่าง|โปรแกรมนี้)", text):
        return result("close_window")

    # --- เพลง / เสียง ---
    if has_any(text, ["หยุดเพลง", "พักเพลง", "เล่นต่อ", "หยุดชั่วคราว"]):
        return result("pause_music")
    if has_any(text, ["ข้ามเพลง", "เพลงถัดไป", "เพลงต่อไป", "เปลี่ยนเพลง"]):
        return result("next_music")
    if has_any(text, ["เพลงก่อนหน้า", "ย้อนเพลง", "เพลงที่แล้ว"]):
        return result("prev_music")
    if has_any(text, ["เพิ่มเสียง", "เสียงดังขึ้น"]):
        return result("volume_up")
    if has_any(text, ["ลดเสียง", "เสียงเบาลง"]):
        return result("volume_down")
    if has_any(text, ["ปิดเสียง", "เปิดเสียง"]):
        return result("mute_audio")
    if has_any(text, ["หาเพลง", "เปิดเพลง", "ขอเพลง"]):
        return result("play_music", music_query(text))

    # --- โปรแกรม ---
    if has_any(text, ["youtube", "you tube", "ยูทูป", "ยูทูบ", "ยูทิวบ์"]):
        return toggle("youtube")
    if "notepad" in text or "สมุดบันทึก" in text:
        return toggle("notepad")
    if "chrome" in text or "เบราว์เซอร์" in text:
        return toggle("chrome")
    if has_any(text, ["เครื่องคิดเลข", "คำนวณ"]):
        return result("open_calc")
    if has_any(text, ["กี่โมง", "เวลาเท่าไร", "เวลาเท่าไหร่"]):
        return result("get_time")
    if has_any(text, ["ล็อกหน้าจอ", "ล็อกคอม"]):
        return result("lock_screen")
    return dict(UNKNOWN)

def interpret(text):
    basic = interpret_basic(text)
    if basic["intent"] != "unknown":
        return basic

    reply = knowledge.local_answer(text)
    if reply:
        return {"intent": "answer", "query": "", "answer": reply}

    if not llm.llm_available():
        print("ℹ️ ยังไม่ได้ตั้ง GROQ_API_KEY / GEMINI_API_KEY จึงตอบได้เฉพาะคำสั่งพื้นฐาน")
        return dict(UNKNOWN)

    data = llm.ask(text)
    if data["intent"] == "answer" and data.get("cacheable"):
        knowledge.remember(text, data["answer"])    # ครั้งหน้าไม่ต้องเรียก LLM อีก
    return data

# =====================================================================
# Command Handlers
# =====================================================================
CONFIRM_YES = ["ยืนยัน", "ใช่", "ตกลง", "เอาเลย", "โอเค", "ok"]
CONFIRM_NO = ["ไม่", "ยกเลิก", "หยุด"]

def confirm(question):
    speak(question)
    reply = record_and_recognize("พูดว่า 'ยืนยัน' หรือ 'ยกเลิก'...")
    return has_any(reply, CONFIRM_YES) and not has_any(reply, CONFIRM_NO)

def run_and_say(message, action):
    def handler(_query):
        speak(message)
        with GUI_LOCK:
            action()
    return handler

def paste_text(text):
    """pyautogui.write พิมพ์ภาษาไทยไม่ได้ จึงใช้วิธีคัดลอกแล้ววาง"""
    pyperclip.copy(text)
    with GUI_LOCK:
        pyautogui.hotkey("ctrl", "v")

def wait_for_window(keyword, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        _, title = active_window_info()
        if keyword in title.lower():
            return True
        time.sleep(0.2)
    return False

def cmd_play_music(query):
    if not query:
        speak("ต้องการฟังเพลงอะไรครับ")
        answer = record_and_recognize("พูดชื่อเพลงได้เลย (ไม่ต้องเรียกชื่อ)...")
        query = music_query(strip_wake_words(answer))
    if query:
        play_new_query(query)
    else:
        speak("ไม่ได้ยินชื่อเพลงครับ ลองใหม่อีกครั้งนะครับ")

def cmd_close_youtube(_query):
    with GUI_LOCK:
        if focus_youtube_window():
            pyautogui.hotkey("ctrl", "w")
            speak("ปิดแท็บ YouTube ให้แล้วครับ")
        else:
            speak("ไม่พบแท็บ YouTube ที่เปิดอยู่ครับ")

def cmd_get_time(_query):
    now = datetime.datetime.now()
    speak(f"เวลาปัจจุบันคือ {now.strftime('%H:%M')} น.",
          say=f"ตอนนี้เวลา {now.hour} นาฬิกา {now.minute} นาทีครับ")

def cmd_get_date(query):
    try:
        offset = int(query)
    except (TypeError, ValueError):
        offset = 0
    d = datetime.date.today() + datetime.timedelta(days=offset)
    label = {-1: "เมื่อวานนี้", 0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}.get(offset, "วันนั้น")
    speak(f"{label}เป็น{DAYS_TH[d.weekday()]}ที่ {d.day} {MONTHS_TH[d.month - 1]} พ.ศ. {d.year + 543} ครับ")

def cmd_check_specific_date(query):
    numbers = re.findall(r"\d+", query)
    if not numbers:
        speak("ไม่พบวันที่ที่ต้องการทราบครับ")
        return
    target_day = int(numbers[0])
    now = datetime.datetime.now()
    try:
        target = datetime.date(now.year, now.month, target_day)
    except ValueError:
        speak("เดือนนี้ไม่มีวันที่ตามที่ระบุครับ")
        return
    speak(f"วันที่ {target_day} {MONTHS_TH[now.month - 1]} เป็น{DAYS_TH[target.weekday()]}ครับ")

def cmd_write_notepad(query):
    if not query:
        speak("ต้องการให้บันทึกข้อความว่าอะไรครับ")
        answer = record_and_recognize("พูดข้อความที่ต้องการบันทึก...")
        query = strip_phrases(strip_wake_words(answer), ["บันทึก", "จดจำ", "เขียนว่า"])
    if not query:
        speak("ไม่ได้ยินข้อความที่ต้องการบันทึกครับ")
        return
    if pyperclip is None:
        print("❌ ต้องติดตั้งก่อน: pip install pyperclip")
        speak("ต้องติดตั้งโมดูล pyperclip ก่อนครับ ถึงจะพิมพ์ภาษาไทยลง Notepad ได้")
        return

    speak("กำลังบันทึกข้อความลงใน Notepad ครับ")
    os.system("start notepad")
    wait_for_window("notepad")          # รอจน Notepad ขึ้นมาอยู่หน้าสุดจริงๆ แทนการเดาเวลา
    time.sleep(0.3)
    paste_text(query)

def cmd_save_note(query):
    if not query:
        speak("ต้องการให้บันทึกข้อความอะไรลงไฟล์ครับ")
        answer = record_and_recognize("พูดข้อความที่ต้องการบันทึก...")
        query = strip_phrases(strip_wake_words(answer), ["บันทึกใส่ไฟล์", "บันทึกลงไฟล์", "สร้างโน้ต"])
    if not query:
        speak("ไม่ได้ยินข้อความครับ")
        return
    filename = os.path.join(BASE_DIR, "my_notes.txt")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {query}\n")
    speak("บันทึกข้อความลงไฟล์โน้ตให้เรียบร้อยแล้วครับ")

def cmd_shutdown(_query):
    if confirm("ยืนยันปิดเครื่องไหมครับ"):
        speak("จะปิดเครื่องใน 30 วินาทีครับ หากต้องการยกเลิกให้พูดว่า ราฟาเอล ยกเลิกปิดเครื่อง")
        os.system("shutdown /s /t 30")
    else:
        speak("ยกเลิกการปิดเครื่องแล้วครับ")

def cmd_restart(_query):
    if confirm("ยืนยันรีสตาร์ทเครื่องไหมครับ"):
        speak("จะรีสตาร์ทเครื่องใน 30 วินาทีครับ หากต้องการยกเลิกให้พูดว่า ราฟาเอล ยกเลิกรีสตาร์ท")
        os.system("shutdown /r /t 30")
    else:
        speak("ยกเลิกการรีสตาร์ทแล้วครับ")

def cmd_set_reminder(query):
    found = reminder.parse_request(query)
    if found is None and llm.llm_available():
        print("🧠 อ่านเวลาไม่ออกด้วยกฎ ให้ LLM ช่วยแปลง...")
        found = llm.parse_reminder(query)
        if found and not found["message"]:
            found["message"] = reminder.clean_message(query, [])
    if found is None:
        speak("ไม่พบเวลาที่ต้องการให้เตือนครับ ลองพูดว่า เตือน 18:00 ไปอาบน้ำ หรือ เตือนอีก 10 นาที ซื้อนม ครับ")
        return

    when = found["when"]
    message = found["message"] or "ตามที่นัดหมาย"
    if when <= datetime.datetime.now():
        speak("เวลานั้นผ่านไปแล้วครับ ลองระบุเวลาใหม่นะครับ")
        return
    reminder.add_reminder(when, message)
    # อ่านเวลากลับให้ฟังเสมอ เผื่อกรณีเวลากำกวม เช่น "6 โมง" ไม่บอกเช้าหรือเย็น
    speak(f"ตั้งเตือน {reminder.spoken_time(when)} เรื่อง {message} เรียบร้อยแล้วครับ")

def cmd_list_reminders(_query):
    pending = reminder.list_pending()
    if not pending:
        speak("ตอนนี้ไม่มีรายการเตือนค้างอยู่ครับ")
        return
    speak(f"มีรายการเตือน {len(pending)} รายการครับ")
    for r in pending[:5]:
        when = datetime.datetime.strptime(r["time"], reminder.FMT)
        speak(f"{reminder.spoken_time(when)} {r['message']}")
    if len(pending) > 5:
        speak(f"และอีก {len(pending) - 5} รายการครับ")

def cmd_cancel_reminders(query):
    pending = reminder.list_pending()
    if not pending:
        speak("ไม่มีรายการเตือนให้ยกเลิกครับ")
        return
    keyword = strip_phrases(query, ["ยกเลิกการเตือน", "ยกเลิกเตือน", "ลบการเตือน", "ลบเตือน",
                                    "ทั้งหมด", "เรื่อง", "เกี่ยวกับ", "หน่อย", "ด้วย"]).strip()
    if keyword:
        removed = reminder.cancel(keyword)
        speak(f"ยกเลิกรายการเตือนเกี่ยวกับ {keyword} จำนวน {removed} รายการแล้วครับ" if removed
              else f"ไม่พบรายการเตือนเกี่ยวกับ {keyword} ครับ")
    elif len(pending) == 1 or confirm(f"มีรายการเตือน {len(pending)} รายการ ยืนยันยกเลิกทั้งหมดไหมครับ"):
        speak(f"ยกเลิกรายการเตือนทั้งหมด {reminder.cancel()} รายการแล้วครับ")
    else:
        speak("ไม่ยกเลิกครับ")

COMMANDS = {
    "close_window": run_and_say("กำลังปิดหน้าต่างปัจจุบันให้ครับ", lambda: pyautogui.hotkey("alt", "f4")),
    "pause_music": run_and_say("สลับหยุดหรือเล่นต่อให้ครับ", lambda: pyautogui.press("playpause")),
    "next_music": lambda _q: play_next(),
    "prev_music": lambda _q: play_prev(),
    "volume_up": run_and_say("เพิ่มเสียงให้ครับ", lambda: pyautogui.press("volumeup", presses=5)),
    "volume_down": run_and_say("ลดเสียงให้ครับ", lambda: pyautogui.press("volumedown", presses=5)),
    "mute_audio": run_and_say("สลับปิดหรือเปิดเสียงให้ครับ", lambda: pyautogui.press("volumemute")),
    "play_music": cmd_play_music,
    "open_youtube": run_and_say("กำลังเปิด YouTube ให้ครับ", lambda: os.system("start chrome https://www.youtube.com")),
    "close_youtube": cmd_close_youtube,
    "open_chrome": run_and_say("กำลังเปิด Google Chrome ให้ครับ", lambda: os.system("start chrome")),
    "close_chrome": run_and_say("กำลังปิด Google Chrome ครับ", lambda: os.system("taskkill /f /im chrome.exe >nul 2>&1")),
    "open_notepad": run_and_say("กำลังเปิด Notepad ให้ครับ", lambda: os.system("start notepad")),
    "close_notepad": run_and_say("กำลังปิด Notepad ครับ", lambda: os.system("taskkill /f /im notepad.exe >nul 2>&1")),
    "open_calc": run_and_say("กำลังเปิดเครื่องคิดเลขให้ครับ", lambda: os.system("start calc")),
    "get_time": cmd_get_time,
    "get_date": cmd_get_date,
    "check_specific_date": cmd_check_specific_date,
    "write_notepad": cmd_write_notepad,
    "save_note": cmd_save_note,
    "lock_screen": run_and_say("กำลังล็อกหน้าจอให้ครับ", lambda: os.system("rundll32.exe user32.dll,LockWorkStation")),
    "shutdown_pc": cmd_shutdown,
    "restart_pc": cmd_restart,
    "set_reminder": cmd_set_reminder,
    "list_reminders": cmd_list_reminders,
    "cancel_reminders": cmd_cancel_reminders,
    "cancel_shutdown": run_and_say("ยกเลิกการปิดเครื่องให้แล้วครับ", lambda: os.system("shutdown /a >nul 2>&1")),
    "sleep_pc": run_and_say("กำลังพักหน้าจอและระบบครับ", lambda: os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")),
}

def handle_command(intent_data, raw_text=""):
    if not isinstance(intent_data, dict):
        intent_data = UNKNOWN
    intent = intent_data.get("intent")
    query = (intent_data.get("query") or "").strip()
    if intent in ("set_reminder", "cancel_reminders") and not query:
        query = raw_text

    if intent == "exit_system":
        speak("ปิดการทำงานผู้ช่วยแล้วครับ สวัสดีครับ")
        return True

    if intent == "answer":
        speak(intent_data.get("answer") or "ขออภัยครับ ผมยังไม่มีคำตอบ")
        return False

    handler = COMMANDS.get(intent)
    if handler:
        handler(query)
    else:
        log_unknown_command(raw_text)
        speak("ยังไม่เข้าใจคำสั่งนี้ครับ บันทึกไว้ให้แล้วครับ")
    return False