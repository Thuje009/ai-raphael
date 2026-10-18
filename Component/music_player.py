"""ระบบค้นหาและควบคุมเพลง/YouTube ของราฟาเอล"""
import os
import re
import time
import pyautogui
import pygetwindow as gw
from yt_dlp import YoutubeDL

try:
    import pyperclip      # จำเป็นสำหรับพิมพ์/ส่ง URL ภาษาไทย
except ImportError:
    pyperclip = None

from common import GUI_LOCK
from speech import speak, record_and_recognize

music = {"queue": [], "index": -1}
BROWSER_NAMES = ("chrome", "edge", "firefox", "brave", "opera")


def search_videos(query, n=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    return [
        (e.get("title", "ไม่ทราบชื่อ"), f"https://www.youtube.com/watch?v={e['id']}")
        for e in (info.get("entries") or [])
        if e and len(str(e.get("id", ""))) == 11
    ]


def find_youtube_windows():
    return [
        w for w in gw.getAllWindows()
        if w.title and "youtube" in w.title.lower()
        and any(b in w.title.lower() for b in BROWSER_NAMES)
    ]


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
            print("⚠️ ยังไม่ได้ติดตั้ง pyperclip (pip install pyperclip)")
        elif focus_youtube_window():
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
    speak("กำลังเล่นเพลงให้ค่ะ")
    open_url(url)


def play_new_query(query):
    speak(f"กำลังค้นหาเพลง {query} ค่ะ")
    try:
        results = search_videos(query)
    except Exception as e:
        print(f"❌ ค้นหาไม่สำเร็จ: {e}")
        speak("ค้นหาเพลงไม่สำเร็จค่ะ")
        return
    if not results:
        speak("ไม่พบเพลงที่ค้นหาค่ะ")
        return
    music["queue"] = results
    play_index(0)


def play_next():
    if not music["queue"]:
        speak("ยังไม่มีคิวเพลงค่ะ ลองสั่งเปิดเพลงก่อนนะคะ")
    elif music["index"] + 1 >= len(music["queue"]):
        speak("หมดคิวเพลงแล้วค่ะ ลองค้นหาเพลงใหม่ได้เลย")
    else:
        play_index(music["index"] + 1)


def play_prev():
    if not music["queue"]:
        speak("ยังไม่มีคิวเพลงค่ะ")
    elif music["index"] <= 0:
        speak("นี่คือเพลงแรกในคิวแล้วค่ะ")
    else:
        play_index(music["index"] - 1)


def music_query(text):
    q = re.sub(r"^(ช่วย|ขอ)", "", text)
    for p in ["ค้นหาเพลง", "หาเพลง", "เปิดเพลง", "ขอเพลง", "ให้ฟังหน่อย", "ให้หน่อย", "หน่อย"]:
        q = q.replace(p, "")
    return q.strip()


def cmd_play_music(query, strip_wake_words_fn):
    if not query:
        speak("ต้องการฟังเพลงอะไรคะ")
        query = music_query(strip_wake_words_fn(record_and_recognize("พูดชื่อเพลงได้เลย...")))
    if query:
        play_new_query(query)
    else:
        speak("ไม่ได้ยินชื่อเพลงค่ะ")


def cmd_close_youtube():
    if focus_youtube_window():
        pyautogui.hotkey("ctrl", "w")
        speak("ปิดแท็บ YouTube ให้แล้วค่ะ")
    else:
        speak("ไม่พบแท็บ YouTube ค่ะ")