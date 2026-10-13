import ctypes
import datetime
import json
import os
import re
import threading
import time

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw
import sounddevice as sd
import speech_recognition as sr
from google import genai
from google.genai import types
from gtts import gTTS
from scipy.io.wavfile import write
from yt_dlp import YoutubeDL

# ทำให้พิกัดภาพแคปหน้าจอ ตรงกับพิกัดเมาส์ เมื่อใช้ Windows scaling (125%, 150%)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =====================================================================
# Config
# =====================================================================
# ---------- Wake word / Gemini ----------
WAKE_WORDS = ("raphael", "rafael", "ราฟาเอล", "ราฟาแอล", "ราฟาเอ็ล", "ราฟา")
WAKE_DISPLAY = "ราฟาเอล"
PREFER_GEMINI = False   # False = จับคำพื้นฐานก่อน เรียก Gemini เฉพาะคำสั่งที่ไม่เข้าใจ
DEBUG_MIC = True
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash"]

# ---------- Ad skipper ----------
SKIP_DIR = os.path.join(BASE_DIR, "Image")
SKIP_IMAGE = os.path.join(BASE_DIR, "skip_btn.png")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
ROI_FILE = os.path.join(BASE_DIR, "player_region.json")

MONITOR_INDEX = 1                      # 1 = จอหลัก, 2 = จอที่สอง
EXCLUDE_SIDEBAR_PX = 480
AUTO_UNDO_MISCLICK = True
BAD_SPOT_RADIUS = 45
MATCH_THRESHOLD = 0.82
HIGH_CONF = 0.92
CONFIRM_FRAMES = 2
SCALES = np.linspace(0.7, 1.5, 7)
REQUIRE_YOUTUBE_FOREGROUND = True
DEBUG_AD_SKIPPER = True
CLICK_COOLDOWN = 3.0                   # วินาที

# =====================================================================
# State
# =====================================================================
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
if client is None:
    print("⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY จะใช้การจับคำแบบพื้นฐานแทน")
    print('   (ตั้งค่าด้วย: setx GEMINI_API_KEY "key-ของคุณ" แล้วเปิดเทอร์มินัลใหม่)')

active_model = {"name": None}
exhausted_models = set()

player_region = {"rect": None}          # (left, top, right, bottom) พิกัดจอจริง
bad_spots = []                          # ตำแหน่งที่เคยคลิกผิด (x, y)
music = {"queue": [], "index": -1}

skipper_stop = threading.Event()
skipper_thread = None


# =====================================================================
# Speech output (gTTS + Windows MCI)
# =====================================================================
def play_mp3(path):
    winmm = ctypes.windll.winmm
    alias = "reply_audio"
    winmm.mciSendStringW(f'open "{os.path.abspath(path)}" type mpegvideo alias {alias}', None, 0, None)
    winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
    winmm.mciSendStringW(f"close {alias}", None, 0, None)


def speak(message, say=None):
    print(message)
    text_to_say = say if say is not None else message
    clean = re.sub(r"[^\w\s\u0E00-\u0E7F.,:'\"-]", "", text_to_say).strip()
    if not clean:
        return

    filename = os.path.join(BASE_DIR, "reply.mp3")
    try:
        gTTS(text=clean, lang="th").save(filename)
        play_mp3(filename)
    except Exception as e:
        print(f"⚠️ พูดไม่สำเร็จ: {e}")
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass


# =====================================================================
# Text helpers
# =====================================================================
def has_close(text):
    """มีคำว่า "ปิด" ที่ไม่ใช่ส่วนหนึ่งของ "เปิด" """
    return re.search(r"(?<!เ)ปิด", text) is not None


def has_open(text):
    return "เปิด" in text


def has_any(text, words):
    return any(w in text for w in words)


def find_wake_word(text):
    return next((w for w in sorted(WAKE_WORDS, key=len, reverse=True) if w in text), None)


def strip_wake_words(text):
    # ตัดคำยาวก่อน กันเหลือเศษคำ เช่น "ราฟาเอล" -> "เอล"
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        text = text.replace(w, "")
    return text.strip()


def strip_phrases(text, phrases):
    for p in phrases:
        text = text.replace(p, "")
    return text.strip()


# =====================================================================
# YouTube / music
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


def focus_youtube_window():
    """โฟกัสหน้าต่าง YouTube แล้วตรวจว่าโฟกัสสำเร็จจริง (กัน Ctrl+W ไปปิดแท็บอื่น)"""
    for w in find_youtube_windows():
        try:
            if w.isMinimized:
                w.restore()
            try:
                w.activate()
            except Exception:
                # pygetwindow มักโยน error ทั้งที่ Windows ไม่ยอมให้แย่งโฟกัส: กด Alt แล้วลองใหม่
                pyautogui.press("alt")
                w.activate()
        except Exception:
            pass
        time.sleep(0.5)
        active, title = active_window_info()
        if "youtube" in title.lower():
            return True
    return False


def open_url(url):
    if focus_youtube_window():
        pyautogui.hotkey("ctrl", "l")
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
# Ad skipper (OpenCV template matching)
# =====================================================================
def youtube_is_foreground():
    try:
        w = gw.getActiveWindow()
        return bool(w and w.title and "youtube" in w.title.lower())
    except Exception:
        return True  # ตรวจไม่ได้ ให้ทำงานต่อไป


def new_screen_grabber():
    # mss เวอร์ชันใหม่ใช้ mss.MSS เวอร์ชันเก่าใช้ mss.mss
    return (getattr(mss, "MSS", None) or mss.mss)()


def dpi_scale():
    try:
        return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
    except Exception:
        return 1.0


def active_window_info():
    """คืน (rect, title) ของหน้าต่างที่โฟกัสอยู่ rect = (left, top, right, bottom)"""
    try:
        w = gw.getActiveWindow()
        if w and w.width > 0:
            return (w.left, w.top, w.left + w.width, w.top + w.height), (w.title or "")
    except Exception:
        pass
    return None, ""


def normalize_title(title):
    """ตัดตัวเลขแจ้งเตือน เช่น "(3) ชื่อคลิป - YouTube" เพื่อไม่ให้นับเป็นการเปลี่ยนหน้า"""
    return re.sub(r"^\(\d+\)\s*", "", title or "").strip()


def list_template_files():
    files = []
    if os.path.isdir(SKIP_DIR):
        files += [os.path.join(SKIP_DIR, n) for n in sorted(os.listdir(SKIP_DIR))
                  if n.lower().endswith(IMAGE_EXTS)]
    if os.path.isfile(SKIP_IMAGE):
        files.append(SKIP_IMAGE)
    return files


def load_templates():
    """คืนค่า list ของ (ชื่อไฟล์, [(รูปที่ปรับสเกลแล้ว, w, h), ...])"""
    loaded = []
    for path in list_template_files():
        name = os.path.basename(path)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"⚠️ อ่านรูปไม่ได้ ข้ามไป: {name}")
            continue
        if img.std() < 12 or min(img.shape[:2]) < 12:
            print(f"⚠️ รูป {name} มีรายละเอียดน้อย/เล็กเกินไป อาจจับพลาดหรือจับมั่ว ลองแคปใหม่ให้พอดีกว่านี้")
        variants = []
        for scale in SCALES:
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            t = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
            th, tw = t.shape[:2]
            if th >= 8 and tw >= 8:
                variants.append((t, tw, th))
        if variants:
            loaded.append((name, variants))
    return loaded






def match_templates(roi_gray, templates):
    """คืน (best_val, best_loc, best_size, best_name, per_template)"""
    best_val, best_loc, best_size, best_name = 0.0, None, (0, 0), ""
    per_template = {}
    rh, rw = roi_gray.shape[:2]
    for name, variants in templates:
        tbest = 0.0
        for t, tw, th in variants:
            if th > rh or tw > rw:
                continue
            res = cv2.matchTemplate(roi_gray, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            tbest = max(tbest, mv)
            if mv > best_val:
                best_val, best_loc, best_size, best_name = mv, ml, (tw, th), name
        per_template[name] = tbest
    return best_val, best_loc, best_size, best_name, per_template



def auto_skip_ads_loop():
    print("👀 RAPHAEL: เริ่มระบบข้ามโฆษณา (สแกนอัตโนมัติเต็มจอ) แล้วค่ะ")

    templates = load_templates()
    if not templates:
        print(f"❌ ไม่มีรูปปุ่มข้ามให้ใช้ (ใส่ไว้ในโฟลเดอร์ {SKIP_DIR})")
        return
    print(f"🖼️ โหลดรูปต้นแบบ {len(templates)} รูป: " + ", ".join(n for n, _ in templates))

    last_click_time = 0.0
    last_debug_time = 0.0

    with new_screen_grabber() as sct:
        while not skipper_stop.is_set():
            try:
                if REQUIRE_YOUTUBE_FOREGROUND and not youtube_is_foreground():
                    skipper_stop.wait(1)
                    continue

                monitor = sct.monitors[MONITOR_INDEX]
                screen_np = np.array(sct.grab(monitor))  # BGRA
                screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_BGRA2GRAY)

                t_start = time.time()
                best_val, best_loc, best_size, best_name, per_template = match_templates(screen_gray, templates)
                now = time.time()

                if DEBUG_AD_SKIPPER and now - last_debug_time > 5:
                    detail = " | ".join(f"{n}={v:.2f}" for n, v in per_template.items())
                    print(f"🔎 AdSkipper: สูงสุด {best_val:.2f} จาก {best_name} (เกณฑ์ {MATCH_THRESHOLD}) "
                          f"สแกน {int((now - t_start) * 1000)} ms\n   แยกรูป: {detail}")
                    last_debug_time = now

                # ถ้าเจอผ่านเกณฑ์และทิ้งช่วงเวลา 3 วินาที คลิกทันที
                if best_val >= MATCH_THRESHOLD and best_loc is not None:
                    if now - last_click_time > 3:
                        tw, th = best_size
                        cx = best_loc[0] + tw // 2 + monitor["left"]
                        cy = best_loc[1] + th // 2 + monitor["top"]

                        print(f"🎯 พบปุ่มข้ามโฆษณา! (ความเหมือน {best_val:.2f}, รูป {best_name}) ที่ X:{cx} Y:{cy}")
                        
                        old_pos = pyautogui.position()
                        pyautogui.click(cx, cy)
                        pyautogui.moveTo(old_pos)
                        
                        last_click_time = now
                        print("⏭️ RAPHAEL: กดข้ามโฆษณาแล้ว")

                skipper_stop.wait(0.3)

            except Exception as e:
                print(f"⚠️ AdSkipper Error: {e}")
                skipper_stop.wait(2)

    print("🛑 RAPHAEL: หยุดระบบข้ามโฆษณาแล้ว")


def start_auto_skip_ads():
    global skipper_thread
    if skipper_thread and skipper_thread.is_alive():
        if not skipper_stop.is_set():
            return True              # กำลังทำงานอยู่แล้ว
        skipper_thread.join(timeout=3)  # รอเธรดเก่าหยุดก่อน กันรันซ้อน
    if not list_template_files():
        print(f"⚠️ ไม่พบรูปปุ่มข้ามโฆษณา ใส่ไว้ในโฟลเดอร์: {SKIP_DIR}")
        return False
    skipper_stop.clear()
    skipper_thread = threading.Thread(target=auto_skip_ads_loop, daemon=True, name="Raphael-AdSkipper")
    skipper_thread.start()
    return True


def stop_auto_skip_ads():
    skipper_stop.set()


# =====================================================================
# Recording + speech recognition
# =====================================================================
def record_and_recognize(prompt_text=None):
    duration, fs = 5, 44100
    filename = os.path.join(BASE_DIR, "temp_audio.wav")

    if prompt_text:
        print(f"\n🎙️ {prompt_text}")
    else:
        print(f"\n🎙️ กำลังสแตนด์บาย... (เรียกชื่อ '{WAKE_DISPLAY}' ก่อนสั่ง  ' ")

    try:
        audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="int16")
        sd.wait()
    except Exception as e:
        print(f"❌ อัดเสียงไม่สำเร็จ: {e}")
        time.sleep(1)
        return ""

    max_volume = int(np.abs(audio_data).max())
    if DEBUG_MIC:
        print(f"🎚️ ระดับเสียงสูงสุด: {max_volume} (เบา <500, ปกติ 3000-20000, แตก ~32767)")
    if max_volume >= 32000:
        print("⚠️ เสียงแตก (clipping) Google จะฟังไม่รู้เรื่อง ลดความดังไมค์ใน Windows เหลือ ~50-70% "
              "และปิด Microphone Boost / ใช้หูฟังเพื่อไม่ให้ไมค์รับเสียงเพลงจากลำโพง")
    if max_volume < 500:
        gain = min(8, 12000 / max(max_volume, 1))
        audio_data = np.clip(audio_data.astype(np.float32) * gain, -32768, 32767).astype(np.int16)

    write(filename, fs, audio_data)
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10  # ไม่ใส่ = รอ Google ไม่จำกัดเวลา โปรแกรมค้างได้
    try:
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language="th-TH").lower()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ: {e}")
        return ""
    except Exception as e:  # เช่น timeout ระหว่างรอ Google
        print(f"❌ รู้จำเสียงไม่สำเร็จ: {type(e).__name__}: {e}")
        return ""
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass


# =====================================================================
# Intent interpretation
# =====================================================================
# =====================================================================
# INTENT INTERPRETATION
# =====================================================================
UNKNOWN = {"intent": "unknown", "query": ""}

INTENT_PROMPT = """คุณคือสมองกลผู้ช่วยสำหรับควบคุม Windows วิเคราะห์คำสั่งผู้ใช้ แล้วตอบเป็น JSON ตามรูปแบบนี้เท่านั้น
คำสั่งผู้ใช้: "{text}"
รูปแบบ JSON:
{{
  "intent": "play_music" | "next_music" | "prev_music" | "pause_music" | "volume_up" | "volume_down" | "mute_audio" | "open_youtube" | "close_youtube" | "open_notepad" | "close_notepad" | "open_chrome" | "close_chrome" | "open_calc" | "get_time" | "lock_screen" | "close_window" | "exit_system" | "unknown",
  "query": "ชื่อเพลงหรือสิ่งที่ต้องค้นหา (ถ้าไม่มีให้เป็นสตริงว่าง)"
}}"""


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
            # ตรวจสอบว่าเป็น Error เกี่ยวกับโควตาหรือเซิร์ฟเวอร์หนาแน่นหรือไม่
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                print(f"⚠️ โควตา Gemini ของโมเดล {model} หมดแล้ว สลับไปใช้ระบบพื้นฐานอัตโนมัติ")
            elif "503" in msg or "UNAVAILABLE" in msg:
                print(f"⚠️ โมเดล {model} คนใช้งานเยอะชั่วคราว (503) สลับไปใช้ระบบพื้นฐานอัตโนมัติ")
            else:
                print(f"⚠️ Gemini API Error: {e}")
            exhausted_models.add(model)
            
    # ถ้า Gemini ทุกตัวพัง หรือติดโควตา/คนเยอะ จะคืนค่าว่างเพื่อให้ระบบสลับไปใช้ Basic Intent ทันที
    return dict(UNKNOWN)


def interpret_basic(text):
    opening, closing = has_open(text), has_close(text)

    def result(intent, query=""):
        return {"intent": intent, "query": query}

    def toggle(base):
        return result(f"close_{base}" if closing and not opening else f"open_{base}")

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
    # 1. ลองใช้ Gemini ก่อน (ถ้าตั้งค่า API ไว้)
    if client is not None:
        result = interpret_with_gemini(text)
        if result.get("intent") and result.get("intent") != "unknown":
            return result
        print("↩️ กำลังสลับมาใช้การจับคำแบบพื้นฐานแทนชั่วคราว...")

    # 2. ถ้า Gemini พัง / ติดโควตา / คนเยอะ หรือไม่ได้ใส่ Key จะใช้ระบบจับคำพื้นฐานทันที
    return interpret_basic(text)



def interpret_basic(text):
    """จับคำแบบพื้นฐาน (ลำดับเงื่อนไขสำคัญ: เช็คคำเฉพาะก่อนคำทั่วไป)"""
    opening, closing = has_open(text), has_close(text)

    def result(intent, query=""):
        return {"intent": intent, "query": query}

    def toggle(base):
        return result(f"close_{base}" if closing and not opening else f"open_{base}")
    # (?<!เ) กัน "เปิดระบบ" ที่มี "ปิดระบบ" ซ่อนอยู่
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
    if has_any(text, ["youtube", "you tube", "ยูทูป", "ยูทูบ", "ยูทูฟ", "ยูทิวบ์", "ยูทิวบ"]):
        return toggle("youtube")
    if "notepad" in text or "สมุดบันทึก" in text:
        return toggle("notepad")
    if "chrome" in text or "เบราว์เซอร์" in text:
        return toggle("chrome")
    if has_any(text, ["เครื่องคิดเลข", "คำนวณ"]):
        return result("open_calc")
    if has_any(text, ["กี่โมง", "เวลาเท่าไร", "ตอนนี้เวลา"]):
        return result("get_time")
    if has_any(text, ["ล็อกหน้าจอ", "ล็อกคอม"]):
        return result("lock_screen")
    return dict(UNKNOWN)


def interpret(text):
    if PREFER_GEMINI:
        result = interpret_with_gemini(text)
        if result.get("intent") not in (None, "unknown"):
            return result
        fallback = interpret_basic(text)
        if fallback["intent"] != "unknown":
            print("↩️ ใช้การจับคำพื้นฐานแทน")
            return fallback
        return result

    basic = interpret_basic(text)
    return basic if basic["intent"] != "unknown" else interpret_with_gemini(text)


# =====================================================================
# Command handlers
# =====================================================================
def run_and_say(message, action):
    """พูดแล้วทำ action"""
    def handler(_query):
        speak(message)
        action()
    return handler


def cmd_play_music(query):
    if not query:
        # ถามต่อและฟังคำตอบทันที ไม่ต้องเรียกชื่อซ้ำ
        speak("ต้องการฟังเพลงอะไรครับ")
        answer = record_and_recognize("พูดชื่อเพลงได้เลย (ไม่ต้องเรียกชื่อ)...")
        query = strip_phrases(strip_wake_words(answer), ["เปิดเพลง", "หาเพลง", "ขอเพลง"])
    if query:
        play_new_query(query)
    else:
        speak("ไม่ได้ยินชื่อเพลงครับ ลองเรียกใหม่อีกครั้งนะครับ")


def cmd_close_youtube(_query):
    # ปิดเฉพาะแท็บ YouTube ไม่ปิด Chrome ทั้งหมด
    if focus_youtube_window():
        pyautogui.hotkey("ctrl", "w")
        speak("ปิดแท็บ YouTube ให้แล้วครับ")
    else:
        print("ℹ️ หาแท็บ YouTube ไม่เจอ (ชื่อหน้าต่างจะแสดงเฉพาะแท็บที่เปิดอยู่ตรงหน้า "
              "ถ้า YouTube อยู่แท็บที่ซ่อนอยู่ จะหาไม่เจอ)")
        speak("ไม่พบแท็บ YouTube ที่เปิดอยู่ครับ")


def cmd_get_time(_query):
    now = datetime.datetime.now()
    speak(f"เวลาปัจจุบันคือ {now.strftime('%H:%M')} น.",
          say=f"ตอนนี้เวลา {now.hour} นาฬิกา {now.minute} นาทีครับ")


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
}


def handle_command(intent_data):
    """คืน True ถ้าต้องออกจากโปรแกรม"""
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
        speak("ขออภัยครับ ยังไม่เข้าใจคำสั่งนี้ ลองใหม่อีกครั้งนะครับ")
    return False


# =====================================================================
# Main
# =====================================================================
def run_command_text(text):
    """วิเคราะห์ข้อความคำสั่ง แล้วรัน คืน True ถ้าต้องออก"""
    result = interpret(text)
    print(f"🤖 ผลลัพธ์: {result}")
    return handle_command(result)


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

                    if handle_command(intent_result):
                        break
                else:
                    speak("ครับ มีอะไรให้ช่วยไหมครับ")
                    follow_up = record_and_recognize("พูดคำสั่งได้เลย (ไม่ต้องเรียกชื่อ)...")
                    if follow_up:
                        intent_result = interpret(strip_wake_words(follow_up))
                        print(f"🤖 ผลลัพธ์: {intent_result}")
                        if handle_command(intent_result):
                            break
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานด้วย Ctrl+C")
    finally:
        stop_auto_skip_ads()


if __name__ == "__main__":
    main()