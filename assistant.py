import datetime
import os
import re
import time
import winreg

#import in Component
import Component.note_manager
import Component.music_player
import Component.system_control
import Component.time_reminder
import Component.app_manager
import Component.macro_manager
import Component.translator
import Component.pc_monitor

import pyautogui
import pygetwindow as gw
from yt_dlp import YoutubeDL

try:
    import pyperclip      # pip install pyperclip (จำเป็นสำหรับพิมพ์ข้อความภาษาไทย)
except ImportError:
    pyperclip = None

import conversation
import knowledge
import llm
from common import GUI_LOCK
from config import BASE_DIR, WAKE_WORDS, FILE_MATCH_THRESHOLD
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

# =====================================================================
# Dynamic App Scanner: implementation lives in Component.app_manager.py.
def get_installed_apps():
    return Component.app_manager.installed_apps()

# =====================================================================
# Intent Interpretation
# =====================================================================
def music_query(text):
    q = Component.time_reminder.strip_phrases(text, ["ค้นหาเพลง", "หาเพลง", "เปิดเพลง", "ขอเพลง", "ให้ฟังหน่อย", "ให้หน่อย", "หน่อย"])
    return re.sub(r"^(ช่วย|ขอ)", "", q).strip()
# =====================================================================
# interpret_basic
# =====================================================================
def interpret_basic(text):
    # ลำดับของ if มีผล: อันที่เจอก่อนจะชนะ จึงเรียงกลุ่มตามความสำคัญ ไม่ใช่ตามตัวอักษร
    opening, closing = has_open(text), has_close(text)

    def result(intent, query=""):
        return {"intent": intent, "query": query}

    def toggle(base):
        return result(f"close_{base}" if closing and not opening else f"open_{base}")

    # =====================================================================
    # 1) สถานะเครื่อง
    # =====================================================================
    if has_any(text, [
        "สถานะเครื่อง", "เช็คเครื่อง", "เช็กเครื่อง", "เช็คคอม", "เช็กคอม",
        "แรมเหลือ", "ซีพียู", "พื้นที่ว่าง", "ตรวจสอบเครื่อง", "เช็คสถานะ",
    ]):
        return result("pc_status")

    # =====================================================================
    # 2) ชุดคำสั่ง (Macro)
    # =====================================================================
    if has_any(text, ["เริ่มโหมด", "เปิดโหมด", "ชุดคำสั่ง"]):
        return result("run_macro", text)

    # =====================================================================
    # 3) ยกเลิกการปิดเครื่อง/รีสตาร์ท
    #    (ต้องอยู่ก่อนหมวด "ควบคุมเครื่อง" ไม่งั้นจะโดนจับเป็น shutdown)
    # =====================================================================
    if has_any(text, ["ยกเลิกปิดเครื่อง", "ยกเลิกการปิดเครื่อง", "ยกเลิกรีสตาร์ท", "ยกเลิกการรีสตาร์ท"]):
        return result("cancel_shutdown")

    # =====================================================================
    # 4) การเตือน (Reminder)
    #    (ต้องอยู่ก่อนหมวดอื่น เพราะ "เตือนให้ปิดเครื่อง" ต้องเป็นการตั้งเตือน ไม่ใช่ปิดเครื่องจริง)
    # =====================================================================
    if has_any(text, ["ยกเลิกเตือน", "ยกเลิกการเตือน", "ลบเตือน", "ลบการเตือน"]):
        return result("cancel_reminders", text)
    if has_any(text, ["มีเตือนอะไร", "เตือนอะไรบ้าง", "รายการเตือน", "ดูการเตือน", "ดูเตือน", "เตือนอะไรไว้"]):
        return result("list_reminders")
    if re.search(r"(?<!คำ)เตือน(?!ภัย)", text):
        return result("set_reminder", text)

    # =====================================================================
    # 5) แปลภาษา
    # =====================================================================
    if has_any(text, ["แปลภาษา", "แปลตรงนี้", "แปลข้อความ", "แปลให้หน่อย", "แปลว่าอะไร"]):
        return result("translate_text")

    # =====================================================================
    # 6) โน้ต / บันทึก
    # =====================================================================
    if has_any(text, [
        "เปิดโน้ต", "เปิดสมุดโน้ต", "ดูโน้ต", "อ่านโน้ต", "โน้ตที่บันทึก", "บันทึกเมื่อกี้",
    ]):
        return result("read_notes")
    # คำว่า "บันทึก" ตัวเดี่ยวครอบคลุมทุกคำในลิสต์นี้แล้ว (ใส่ไว้เพื่ออ่านง่าย)
    if has_any(text, [
        "บันทึกลงไฟล์", "บันทึกใส่ไฟล์", "จดลงไฟล์", "สร้างโน้ต", "จดโน้ต",
        "บันทึกข้อมูล", "บันทึกโน้ต", "บันทึกข้อความ", "บันทึก",
    ]):
        return result("save_note", Component.time_reminder.strip_phrases(text, [
            "บันทึกลงไฟล์", "บันทึกใส่ไฟล์", "จดลงไฟล์", "สร้างโน้ต", "จดโน้ต",
            "บันทึกข้อมูล", "บันทึกโน้ต", "ให้หน่อย", "หน่อย",
        ]))

    # =====================================================================
    # 7) วันที่ / เวลา
    # =====================================================================
    if re.search(r"\d", text) and has_any(text, ["วันอะไร", "เป็นวัน"]):
        return result("check_specific_date", text)
    if has_any(text, [
        "วันนี้วันอะไร", "วันอะไรแล้ว", "วันที่เท่าไร", "วันที่เท่าไหร่", "วันนี้วันที่",
        "พรุ่งนี้วันอะไร", "เมื่อวานวันอะไร", "มะรืนวันอะไร",
    ]):
        offset = 1 if "พรุ่งนี้" in text else -1 if "เมื่อวาน" in text else 2 if "มะรืน" in text else 0
        return result("get_date", str(offset))
    if has_any(text, ["กี่โมง", "เวลาเท่าไร", "เวลาเท่าไหร่"]):
        return result("get_time")

    # =====================================================================
    # 8) เพลง
    # =====================================================================
    if re.match(r"^\s*(?:ช่วย)?(?:เปิด|หา|ขอ)เพลง(?!ต่อไป|ถัดไป|ก่อนหน้า|ที่แล้ว)", text):
        return result("play_music", music_query(text))
    if has_any(text, ["หยุดเพลง", "พักเพลง", "เล่นต่อ", "หยุดชั่วคราว"]):
        return result("pause_music")
    if has_any(text, ["ข้ามเพลง", "เพลงถัดไป", "เพลงต่อไป", "เปลี่ยนเพลง"]):
        return result("next_music")
    if has_any(text, ["เพลงก่อนหน้า", "ย้อนเพลง", "เพลงที่แล้ว"]):
        return result("prev_music")

    # =====================================================================
    # 9) ระดับเสียง
    # =====================================================================
    if has_any(text, ["เพิ่มเสียง", "เสียงดังขึ้น"]):
        return result("volume_up")
    if has_any(text, ["ลดเสียง", "เสียงเบาลง"]):
        return result("volume_down")
    if has_any(text, ["ปิดเสียง", "เปิดเสียง"]):
        return result("mute_audio")

    # =====================================================================
    # 10) ควบคุมเครื่อง (ระบบ)
    # =====================================================================
    if has_any(text, ["ปิดเครื่อง", "ดับเครื่อง", "shutdown"]):
        return result("shutdown_pc")
    if has_any(text, ["รีสตาร์ท", "รีเครื่อง", "restart"]):
        return result("restart_pc")
    if has_any(text, ["พักเครื่อง", "สลีป", "sleep pc"]):
        return result("sleep_pc")
    if has_any(text, ["ล็อกหน้าจอ", "ล็อกคอม"]):
        return result("lock_screen")
    if has_any(text, ["สแกนไวรัส", "ตรวจไวรัส", "หาไฟล์อันตราย", "เช็กไวรัส", "สแกนเครื่อง"]):
        return result("scan_virus")

    # =====================================================================
    # 11) ควบคุมราฟาเอล (ปิดโปรแกรมตัวเอง)
    # =====================================================================
    if has_any(text, ["หยุดการทำงาน", "ออกจากโปรแกรม"]) or re.search(r"(?<!เ)ปิดระบบ", text):
        return result("exit_system")

    # =====================================================================
    # 12) ควบคุมหน้าต่าง
    #     "ปิดหน้าต่างอื่น..." ต้องเช็กก่อน "ปิดหน้าต่าง" เฉย ๆ
    #     ไม่งั้นจะโดนจับเป็น close_window ก่อนเสมอ
    # =====================================================================
    if has_any(text, ["ปิดหน้าต่างอื่น", "ปิดหน้าต่างทั้งหมด", "ปิดทุกหน้าต่าง", "เคลียร์หน้าจอ", "ปิดทุกอย่างยกเว้น"]):
        return result("close_other_windows", text)
    if re.search(r"(?<!เ)ปิด(หน้าต่าง|โปรแกรมนี้)", text):
        return result("close_window")

    # =====================================================================
    # 13) เปิด/ปิดโปรแกรมที่กำหนดไว้
    # =====================================================================
    if has_any(text, ["youtube", "you tube", "ยูทูป", "ยูทูบ", "ยูทิวบ์"]):
        return toggle("youtube")
    if "notepad" in text or "สมุดบันทึก" in text:
        return toggle("notepad")
    if "chrome" in text or "เบราว์เซอร์" in text:
        return toggle("chrome")
    if has_any(text, ["เครื่องคิดเลข", "คำนวณ"]):
        return result("close_app" if closing and not opening else "open_calc", "Calculator")
    if has_any(text, ["explorer", "folder", "โฟลเดอร์", "แฟ้ม", "ไฟล์แวร์"]):
        return toggle("explorer")
    if has_any(text, ["setting", "ตั้งค่า", "การตั้งค่า"]):
        return toggle("settings")
    if has_any(text, ["control panel", "คอนโทรลพาเนล", "แผงควบคุม"]):
        return toggle("control_panel")

    # =====================================================================
    # 14) ค้นหาข้อมูลออนไลน์
    # =====================================================================
    m = re.match(r"^\s*(?:ช่วย)?(?:ค้นหา|ค้นข้อมูล|ค้นให้|สืบค้น|เสิร์ช|search)\s*(?:ข้อมูล)?\s*(?:เกี่ยวกับ|เรื่อง)?", text)
    if m:
        return result("live_search", text[m.end():].strip() or text)

    # =====================================================================
    # 15) โปรแกรมทั่วไป (ตัวสุดท้าย: จับ "เปิด/ปิด <ชื่อโปรแกรมอะไรก็ได้>")
    #     ต้องอยู่ท้ายสุดเสมอ เพราะกฎด้านบนเฉพาะเจาะจงกว่า
    # =====================================================================
    m = re.match(r"^\s*(?:ช่วย)?(เปิด|ปิด)(?:โปรแกรม|แอป|แอพ)?\s*(.+?)\s*(?:ให้หน่อย|หน่อย)?\s*$", text)
    if m:
        target = m.group(2).strip()
        if target:
            return result("open_app" if m.group(1) == "เปิด" else "close_app", target)

    return dict(UNKNOWN)


SEARCH_FAIL_REPLY = "รายงานค่ะ ดิฉันค้นข้อมูลสดไม่สำเร็จในตอนนี้ ลองใหม่อีกครั้งภายหลังนะคะ"
SEARCH_OFF_REPLY = "รายงานค่ะ ตอนนี้ดิฉันค้นข้อมูลสดไม่ได้ อาจยังไม่ได้ตั้งค่า หรือใช้โควต้าของวันนี้ครบแล้วค่ะ"

def _answered(text, reply):
    conversation.add(text, reply)
    return {"intent": "answer", "query": "", "answer": reply}

def _search_reply(question, history, original=None):
    if not llm.live_search_available(): return None
    print("🌐 ค้นข้อมูลสดผ่าน Google Search...")
    reply = llm.search_answer(question, history)
    return _answered(original or question, reply) if reply else None

def interpret(text):
    basic = interpret_basic(text)
    if basic["intent"] == "live_search":
        return (_search_reply(basic["query"], conversation.recent(), original=text) or _answered(text, SEARCH_FAIL_REPLY if llm.live_search_available() else SEARCH_OFF_REPLY))
    if basic["intent"] != "unknown": return basic

    reply = knowledge.rule_answer(text)
    if reply: return _answered(text, reply)

    history = conversation.recent()
    followup = conversation.is_followup(text)
    context, source, raw_fallback = None, None, None

    if not followup:
        cached = knowledge.cache_answer(text)
        if cached: return _answered(text, cached)
        chunks = knowledge.retrieve(text)
        if chunks:
            context, source = [c for c, _s in chunks], "file"
            if chunks[0][1] >= FILE_MATCH_THRESHOLD: raw_fallback = knowledge.shorten(chunks[0][0])
        elif knowledge.looks_factual(text) and not knowledge.needs_live_data(text):
            wiki = knowledge.wiki_answer(text)
            if wiki: context, source, raw_fallback = [wiki], "wiki", wiki

    if source != "file" and knowledge.needs_live_data(text):
        found = _search_reply(text, history)
        if found: return found
        return _answered(text, knowledge.LIVE_DATA_REPLY)

    if not llm.llm_available():
        return _answered(text, raw_fallback) if raw_fallback else dict(UNKNOWN)

    data = llm.ask(text, history=history, context=context, tier=llm.choose_tier(text, bool(context)))
    if data["intent"] == "live_search":
        return (_search_reply(data.get("query") or text, history, original=text) or _answered(text, knowledge.LIVE_DATA_REPLY))
    if data["intent"] == "answer":
        if source == "file" or followup: data["cacheable"] = False
        if data.get("cacheable"): knowledge.remember(text, data["answer"])
        conversation.add(text, data["answer"])
    elif data["intent"] == "unknown" and raw_fallback:
        return _answered(text, raw_fallback)
    return data

CONFIRM_YES, CONFIRM_NO = ["ยืนยัน", "ใช่", "ตกลง", "เอาเลย", "โอเค", "ok"], ["ไม่", "ยกเลิก", "หยุด"]

def confirm(question):
    speak(question)
    return has_any(record_and_recognize("พูดว่า 'ยืนยัน' หรือ 'ยกเลิก'..."), CONFIRM_YES) and not has_any(record_and_recognize(), CONFIRM_NO)

def run_and_say(message, action):
    return lambda _q: (speak(message), GUI_LOCK.acquire(), action(), GUI_LOCK.release()) if hasattr(GUI_LOCK, 'acquire') else lambda _q: (speak(message), action())

def paste_text(text):
    pyperclip.copy(text)
    with GUI_LOCK: pyautogui.hotkey("ctrl", "v")

def cmd_save_note(query):
  Component.note_manager.interactive_note_session(query) 

def cmd_open_app(query):
    if not query:
        speak("ต้องการเปิดโปรแกรมอะไรคะ")
        return
    ok, detail = Component.app_manager.open_app(query)
    speak(f"กำลังเปิด {detail} ให้ค่ะ" if ok else f"เปิด {query} ไม่สำเร็จค่ะ {detail}")

def cmd_close_app(query):
    if not query:
        speak("ต้องการปิดโปรแกรมอะไรคะ")
        return
    if Component.app_manager.canonical(query) == "file explorer":
        Component.system_control.close_explorer_windows()
        speak("ส่งคำสั่งปิดหน้าต่าง File Explorer แล้วค่ะ")
        return
    ok, detail = Component.app_manager.close_app(query)
    speak(f"ส่งคำสั่งปิด {detail} แล้วค่ะ" if ok else f"ปิด {query} ไม่สำเร็จค่ะ {detail}")

# =====================================================================
# COMMANDS Dictionary
# =====================================================================

COMMANDS = {
    # =====================================================================
    # 1) เพลง
    # =====================================================================
    "play_music": lambda q: Component.music_player.cmd_play_music(q, strip_wake_words),
    "pause_music": run_and_say(
        "สลับหยุดหรือเล่นต่อให้ค่ะ", lambda: pyautogui.press("playpause")
    ),
    "next_music": lambda _q: Component.music_player.play_next(),
    "prev_music": lambda _q: Component.music_player.play_prev(),

    # =====================================================================
    # 2) ระดับเสียง
    # =====================================================================
    "volume_up": run_and_say(
        "เพิ่มเสียงให้ค่ะ", lambda: pyautogui.press("volumeup", presses=5)
    ),
    "volume_down": run_and_say(
        "ลดเสียงให้ค่ะ", lambda: pyautogui.press("volumedown", presses=5)
    ),
    "mute_audio": run_and_say(
        "สลับปิดหรือเปิดเสียงให้ค่ะ", lambda: pyautogui.press("volumemute")
    ),

    # =====================================================================
    # 3) ควบคุมหน้าต่าง
    # =====================================================================
    "close_window": run_and_say(
        "กำลังปิดหน้าต่างปัจจุบันให้ค่ะ",
        lambda: pyautogui.hotkey("alt", "f4"),
    ),
    "close_other_windows": run_and_say(
        "กำลังปิดหน้าต่างอื่นให้เรียบร้อยค่ะ", Component.system_control.close_other_windows
    ),

    # =====================================================================
    # 4) เปิด/ปิดโปรแกรม
    # =====================================================================
    "open_app": cmd_open_app,
    "close_app": cmd_close_app,

    # --- YouTube ---
    "open_youtube": run_and_say(
        "กำลังเปิด YouTube ให้ค่ะ",
        lambda: os.system("start chrome https://www.youtube.com"),
    ),
    "close_youtube": lambda _q: Component.music_player.cmd_close_youtube(),

    # --- Chrome ---
    "open_chrome": run_and_say(
        "กำลังเปิด Google Chrome ให้ค่ะ", lambda: os.system("start chrome")
    ),
    "close_chrome": run_and_say(
        "กำลังปิด Google Chrome ค่ะ",
        lambda: os.system("taskkill /f /im chrome.exe >nul 2>&1"),
    ),

    # --- Notepad ---
    "open_notepad": run_and_say(
        "กำลังเปิด Notepad ให้ค่ะ", lambda: os.system("start notepad")
    ),
    "close_notepad": run_and_say(
        "กำลังปิด Notepad ค่ะ",
        lambda: os.system("taskkill /f /im notepad.exe >nul 2>&1"),
    ),

    # --- เครื่องคิดเลข ---
    "open_calc": run_and_say(
        "กำลังเปิดเครื่องคิดเลขให้ค่ะ", lambda: os.system("start calc")
    ),

    # --- File Explorer ---
    "open_explorer": run_and_say(
        "กำลังเปิด File Explorer ให้ค่ะ", lambda: os.system("start explorer")
    ),
    "close_explorer": run_and_say(
        "กำลังปิด File Explorer ค่ะ", Component.system_control.close_explorer_windows
    ),

    # --- การตั้งค่า ---
    "open_settings": run_and_say(
        "กำลังเปิดการตั้งค่าให้ค่ะ", lambda: os.system("start ms-settings:")
    ),
    "close_settings": run_and_say(
        "กำลังปิดการตั้งค่าค่ะ",
        lambda: os.system("taskkill /f /im SystemSettings.exe >nul 2>&1"),
    ),

    # --- Control Panel ---
    "open_control_panel": run_and_say(
        "กำลังเปิด Control Panel ให้ค่ะ", lambda: os.system("start control")
    ),
    "close_control_panel": run_and_say(
        "กำลังปิด Control Panel ค่ะ", Component.system_control.close_explorer_windows
    ),

    # =====================================================================
    # 5) โน้ต / บันทึก
    # =====================================================================
    "read_notes": Component.note_manager.open_notes_file,
    "save_note": cmd_save_note,
    # "write_notepad": cmd_write_notepad,

    # =====================================================================
    # 6) วันที่ / เวลา
    # =====================================================================
    "get_time": Component.time_reminder.cmd_get_time,
    "get_date": Component.time_reminder.cmd_get_date,
    "check_specific_date": Component.time_reminder.cmd_check_specific_date,

    # =====================================================================
    # 7) การเตือน
    # =====================================================================
    "set_reminder": Component.time_reminder.cmd_set_reminder,
    "list_reminders": Component.time_reminder.cmd_list_reminders,
    "cancel_reminders": Component.time_reminder.cmd_cancel_reminders,

    # =====================================================================
    # 8) ควบคุมเครื่อง (ระบบ)
    # =====================================================================
    "lock_screen": run_and_say(
        "กำลังล็อกหน้าจอค่ะ",
        lambda: os.system("rundll32.exe user32.dll,LockWorkStation"),
    ),
    "sleep_pc": run_and_say(
        "กำลังพักเครื่องค่ะ",
        lambda: os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
    ),
    "shutdown_pc": lambda q: (
        confirm("ยืนยันปิดเครื่องไหมคะ")
        and (
            speak("จะปิดเครื่องใน 30 วินาทีค่ะ"),
            os.system("shutdown /s /t 30"),
        )
    )
    or speak("ยกเลิกการปิดเครื่องค่ะ"),
    "restart_pc": lambda q: (
        confirm("ยืนยันรีสตาร์ทไหมคะ")
        and (
            speak("จะรีสตาร์ทใน 30 วินาทีค่ะ"),
            os.system("shutdown /r /t 30"),
        )
    )
    or speak("ยกเลิกการรีสตาร์ทค่ะ"),
    "cancel_shutdown": run_and_say(
        "ยกเลิกการปิดเครื่องเรียบร้อยค่ะ",
        lambda: os.system("shutdown /a >nul 2>&1"),
    ),

    # =====================================================================
    # 9) ตรวจสอบเครื่อง / ความปลอดภัย
    # =====================================================================
    "pc_status": lambda _q: Component.pc_monitor.check_pc_status(),
    "scan_virus": lambda _q: Component.system_control.scan_virus_in_background(),

    # =====================================================================
    # 10) เครื่องมืออื่น ๆ
    # =====================================================================
    "run_macro": lambda q: Component.macro_manager.run_macro(q),
    "translate_text": lambda _q: Component.translator.translate_selected_text(),
}

def handle_command(intent_data, raw_text=""):
    if not isinstance(intent_data, dict):
        intent_data = UNKNOWN
    intent = intent_data.get("intent")
    query = (intent_data.get("query") or "").strip()
    if intent in ("set_reminder", "cancel_reminders") and not query:
        query = raw_text

    if intent == "exit_system":
        speak("ปิดการทำงานผู้ช่วยแล้วค่ะ สวัสดีค่ะ")
        return True

    if intent == "answer":
        speak(intent_data.get("answer") or "ขออภัยค่ะ ดิฉันยังไม่มีคำตอบ")
        return False

    handler = COMMANDS.get(intent)
    if handler:
        handler(query)
    else:
        log_unknown_command(raw_text)
        if re.search(r"(อะไร|ใคร|ที่ไหน|เมื่อไร|เมื่อไหร่|ทำไม|อย่างไร|ยังไง|ไหม|หรือเปล่า|เท่าไร|เท่าไหร่|กี่)", raw_text):
            speak("รายงานค่ะ ดิฉันจับใจความคำถามนี้ไม่ได้ ลองถามใหม่อีกครั้งได้ไหมคะ")
        else:
            speak("ยังไม่เข้าใจคำสั่งนี้ค่ะ บันทึกไว้ให้แล้วค่ะ")
    return False