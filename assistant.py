import os
import datetime
import json
import re
import pyautogui
import pygetwindow as gw
from yt_dlp import YoutubeDL
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODELS, PREFER_GEMINI, WAKE_WORDS
from speech import speak, record_and_recognize
from logger import log_unknown_command

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
active_model = {"name": None}
exhausted_models = set()
music = {"queue": [], "index": -1}

UNKNOWN = {"intent": "unknown", "query": ""}

INTENT_PROMPT = """คุณคือสมองกลผู้ช่วยสำหรับควบคุม Windows วิเคราะห์คำสั่งผู้ใช้ แล้วตอบเป็น JSON ตามรูปแบบนี้เท่านั้น
คำสั่งผู้ใช้: "{text}"
รูปแบบ JSON:
{{
  "intent": "play_music" | "next_music" | "prev_music" | "pause_music" | "volume_up" | "volume_down" | "mute_audio" | "open_youtube" | "close_youtube" | "open_notepad" | "close_notepad" | "open_chrome" | "close_chrome" | "open_calc" | "get_time" | "lock_screen" | "close_window" | "shutdown_pc" | "restart_pc" | "sleep_pc" | "exit_system" | "unknown",
  "query": "ชื่อเพลงหรือสิ่งที่ต้องค้นหา"
}}"""

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
    return [
        (e.get("title", "ไม่ทราบชื่อ"), f"https://www.youtube.com/watch?v={e['id']}")
        for e in info.get("entries", [])
        if e and e.get("id")
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
        import time
        time.sleep(0.5)
        _, title = active_window_info()
        if "youtube" in title.lower():
            return True
    return False

def open_url(url):
    if focus_youtube_window():
        pyautogui.hotkey("ctrl", "l")
        import time
        time.sleep(0.2)
        pyautogui.write(url, interval=0.01)
        pyautogui.press("enter")
    else:
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
# Intent Interpretation (Gemini + Basic Fallback)
# =====================================================================
def interpret_with_gemini(text):
    if client is None:
        return dict(UNKNOWN)

    prompt = INTENT_PROMPT.format(text=text)
    config = types.GenerateContentConfig(response_mime_type="application/json")
    models = [m for m in GEMINI_MODELS if m not in exhausted_models]

    for model in models:
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            active_model["name"] = model
            data = json.loads(response.text or "{}")
            if isinstance(data, dict) and data.get("intent"):
                return data
            return dict(UNKNOWN)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                print(f"⚠️ โควตา Gemini ของโมเดล {model} หมดแล้ว สลับไปใช้ระบบพื้นฐานอัตโนมัติ")
            elif "503" in msg or "UNAVAILABLE" in msg:
                print(f"⚠️ โมเดล {model} คนใช้งานเยอะชั่วคราว (503) สลับไปใช้ระบบพื้นฐานอัตโนมัติ")
            exhausted_models.add(model)
            
    return dict(UNKNOWN)

def interpret_basic(text):
    opening, closing = has_open(text), has_close(text)

    def result(intent, query=""):
        return {"intent": intent, "query": query}

    def toggle(base):
        return result(f"close_{base}" if closing and not opening else f"open_{base}")
    if has_any(text, ["วันนี้วันอะไร", "วันนั้้นวันอะไร", "วันที่เท่าไร", "วันอะไรแล้ว"]):
        return result("get_date")
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
        query = strip_phrases(text, ["หาเพลง", "เปิดเพลง", "ขอเพลง", "ให้ฟังหน่อย", "ให้หน่อย", "หน่อย"])
        return result("play_music", query)
    if has_any(text, ["youtube", "you tube", "ยูทูป", "ยูทูบ", "ยูทิวบ์"]):
        return toggle("youtube")
    if "notepad" in text or "สมุดบันทึก" in text:
        return toggle("notepad")
    if "chrome" in text or "เบราว์เซอร์" in text:
        return toggle("chrome")
    if has_any(text, ["เครื่องคิดเลข", "คำนวณ"]):
        return result("open_calc")
    if has_any(text, ["กี่โมง", "เวลาเท่าไร"]):
        return result("get_time")
    if has_any(text, ["ล็อกหน้าจอ", "ล็อกคอม"]):
        return result("lock_screen")
    return dict(UNKNOWN)

def interpret(text):
    if PREFER_GEMINI and client is not None:
        result = interpret_with_gemini(text)
        if result.get("intent") and result.get("intent") != "unknown":
            return result
        print("↩️ กำลังสลับมาใช้การจับคำแบบพื้นฐานแทน...")
        return interpret_basic(text)
    
    basic = interpret_basic(text)
    if basic["intent"] != "unknown":
        return basic
    
    if client is not None:
        return interpret_with_gemini(text)
    return basic

# =====================================================================
# Command Handlers
# =====================================================================
def run_and_say(message, action):
    def handler(_query):
        speak(message)
        action()
    return handler

def cmd_play_music(query):
    if not query:
        speak("ต้องการฟังเพลงอะไรครับ")
        answer = record_and_recognize("พูดชื่อเพลงได้เลย (ไม่ต้องเรียกชื่อ)...")
        query = strip_phrases(strip_wake_words(answer), ["เปิดเพลง", "หาเพลง", "ขอเพลง"])
    if query:
        play_new_query(query)
    else:
        speak("ไม่ได้ยินชื่อเพลงครับ ลองใหม่อีกครั้งนะครับ")

def cmd_close_youtube(_query):
    if focus_youtube_window():
        pyautogui.hotkey("ctrl", "w")
        speak("ปิดแท็บ YouTube ให้แล้วครับ")
    else:
        speak("ไม่พบแท็บ YouTube ที่เปิดอยู่ครับ")

def cmd_get_time(_query):
    now = datetime.datetime.now()
    speak(f"เวลาปัจจุบันคือ {now.strftime('%H:%M')} น.",
          say=f"ตอนนี้เวลา {now.hour} นาฬิกา {now.minute} นาทีครับ")

def cmd_get_date(_query):
    now = datetime.datetime.now()
    # แปลงเป็นชื่อวันภาษาไทย
    days_th = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
    day_name = days_th[now.weekday()]
    speak(f"วันนี้คือ{day_name} ที่ {now.day} เดือนนี้ ครับ",
          say=f"วันนี้คือ {day_name} ที่ {now.day} ครับ")

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
    "lock_screen": run_and_say("กำลังล็อกหน้าจอให้ครับ", lambda: os.system("rundll32.exe user32.dll,LockWorkStation")),
    "shutdown_pc": run_and_say("กำลังจะปิดเครื่องใน 10 วินาทีครับ", lambda: os.system("shutdown /s /t 10")),
    "restart_pc": run_and_say("กำลังจะรีสตาร์ทเครื่องใน 10 วินาทีครับ", lambda: os.system("shutdown /r /t 10")),
    "sleep_pc": run_and_say("กำลังพักหน้าจอและระบบครับ", lambda: os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")),
    "get_date": cmd_get_date,
}

def handle_command(intent_data, raw_text=""):
    if not isinstance(intent_data, dict):
        intent_data = UNKNOWN
    intent = intent_data.get("intent")
    query = (intent_data.get("query") or "").strip()

    if intent == "exit_system":
        speak("ปิดการทำงานผู้ช่วยแล้วครับ สวัสดีครับ")
        return True

    handler = COMMANDS.get(intent)
    if handler:
        handler(query)
    else:
        # บันทึกข้อความดิบที่ผู้พูดลงใน Log เมื่อไม่เข้าใจคำสั่ง
        log_unknown_command(raw_text)
        speak("ขออภัยครับ ยังไม่เข้าใจคำสั่งนี้ บันทึกข้อมูลไว้ให้แล้วครับ")
        return False
    return False


