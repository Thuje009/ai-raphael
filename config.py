import os
import numpy as np

# อ่านค่าจากไฟล์ .env ถ้ามี (pip install python-dotenv) ไม่มีก็ข้ามไป
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =====================================================================
# Wake word / Debug
# =====================================================================
WAKE_WORDS = ("raphael", "rafael", "ราฟาเอล", "ราฟาแอล", "ราฟาเอ็ล", "ราฟา")
WAKE_DISPLAY = "ราฟาเอล"
DEBUG_MIC = True

# =====================================================================
# LLM (ลำดับในนี้ = ลำดับที่ลอง: Groq ก่อน แล้วค่อย Gemini)
# รันคำสั่ง `python llm.py` เพื่อดูรายชื่อโมเดลที่ใช้ได้จริงกับ key ของคุณ
# =====================================================================
LLM_PROVIDERS = ("groq", "gemini")
LLM_TIMEOUT_SEC = 8
LLM_MAX_TOKENS = 600          # gpt-oss นับ token ที่ใช้คิดรวมด้วย จึงตั้งเผื่อไว้

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# หมายเหตุ: gemini-2.5-* ปิดบริการวันที่ 16 ต.ค. 2026 จึงไม่ใส่ไว้
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]

# =====================================================================
# Knowledge (ฐานความรู้)
# =====================================================================
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")          # ใส่ไฟล์ .txt / .md ที่อยากให้ตอบได้
KNOWLEDGE_CACHE_FILE = os.path.join(BASE_DIR, "knowledge_cache.json")
KNOWLEDGE_CACHE_MAX = 500
FILE_MATCH_THRESHOLD = 0.55                                  # ยิ่งสูงยิ่งเข้มงวดตอนค้นจากไฟล์
WIKI_LANG = "th"
WIKI_TIMEOUT_SEC = 5

# =====================================================================
# Speech (เสียงพูด / ไมค์)
# =====================================================================
TTS_ENGINE = "gtts"                  # "gtts" = เสียงเดิม (หญิง) | "edge" = edge-tts (ต้องตั้ง TTS_VOICE ด้านล่าง)
# ค่า 3 ตัวถัดไปใช้เฉพาะเมื่อ TTS_ENGINE = "edge"
TTS_VOICE = "th-TH-PremwadeeNeural"  # เสียงผู้หญิง (ผู้ชาย: th-TH-NiwatNeural) ดูรายชื่อทั้งหมด: edge-tts --list-voices
TTS_RATE = "+0%"                     # ความเร็วพูด เช่น "+10%" เร็วขึ้น "-10%" ช้าลง
TTS_PITCH = "+0Hz"                   # ระดับเสียง เช่น "+5Hz" แหลมขึ้น "-5Hz" ทุ้มลง
TTS_CACHE_DIR = os.path.join(BASE_DIR, "tts_cache")
TTS_CACHE_MAX_CHARS = 60             # ประโยคสั้นกว่านี้จะถูก cache ไว้ใช้ซ้ำ

MIC_SAMPLE_RATE = 16000
VAD_MIN_RMS = 120                    # ระดับเสียงต่ำสุดที่นับว่า "กำลังพูด" (ไมค์เบามากให้ลดลง)
VAD_NOISE_RATIO = 3.0                # ต้องดังกว่าเสียงรบกวนพื้นหลังกี่เท่า
VAD_SILENCE_SEC = 1.0                # เงียบนานเท่านี้ = พูดจบ
VAD_MAX_WAIT_SEC = 6.0               # รอเสียงพูดนานสุดต่อรอบ
VAD_MAX_SEC = 12.0                   # อัดนานสุดต่อประโยค

# =====================================================================
# Ad Skipper
# =====================================================================
SKIP_DIR = os.path.join(BASE_DIR, "Image")
SKIP_IMAGE = os.path.join(BASE_DIR, "skip_btn.png")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")

MONITOR_INDEX = 1
SCALES = np.linspace(0.7, 1.5, 7)
# โหมดสแกนปุ่มข้ามโฆษณา
#   "foreground"      = สแกนเฉพาะตอนหน้าต่าง YouTube อยู่ด้านหน้า (ปลอดภัยสุด)
#   "youtube_windows" = สแกนทุกหน้าต่าง YouTube ที่มองเห็นอยู่ แม้ไม่ได้อยู่ด้านหน้า (แนะนำ)
#   "full_screen"     = สแกนทั้งจอ MONITOR_INDEX ตลอดเวลา (กินเครื่องและเสี่ยงคลิกผิดมากสุด)
AD_SCAN_MODE = "youtube_windows"
AD_SCAN_INTERVAL_SEC = 0.3           # สแกนทุกกี่วินาที (เครื่องหน่วงให้เพิ่มเป็น 0.5-1.0)
DEBUG_AD_SKIPPER = True
MATCH_THRESHOLD = 0.82
CLICK_COOLDOWN = 3.0

# ตั้งเป็น 0 ก่อน (คลิกกลางปุ่มพอดี) ถ้ายังคลิกเพี้ยนค่อยปรับ
CLICK_OFFSET_X = 0
CLICK_OFFSET_Y = 0

# =====================================================================
# Reminder (ระบบแจ้งเตือน)
# =====================================================================
REMINDER_CHECK_SEC = 5               # เช็กรายการที่ถึงเวลาทุกกี่วินาที
REMINDER_MAX_REPEAT = 5              # เตือนซ้ำสูงสุดกี่รอบถ้าไม่มีคำตอบ (แล้วบันทึกว่าพลาด)
REMINDER_REPEAT_GAP_SEC = 10         # เว้นกี่วินาทีก่อนเตือนซ้ำ
REMINDER_SNOOZE_MIN = 10             # พูดว่า "เลื่อน" เฉยๆ จะเลื่อนไปกี่นาที
REMINDER_LATE_MIN = 5                # เลยเวลามากกว่านี้ (เช่นเปิดโปรแกรมช้า) จะบอกว่า "เลยเวลามาแล้ว"
REMINDER_KEEP_DAYS = 2               # เก็บรายการที่เตือนแล้วไว้กี่วัน

# =====================================================================
# บุคลิก / ความจำสนทนา / ตอบจากฐานความรู้ (RAG)
# =====================================================================
PERSONA_FEMALE = True                # True = แปลงคำลงท้ายที่พูดทุกประโยคเป็น ค่ะ/คะ (แก้ข้อความบุคลิกที่ persona.py)
MEMORY_TURNS = 4                     # จำบทสนทนาย้อนหลังกี่รอบ (1 รอบ = ถาม 1 ตอบ 1)
MEMORY_IDLE_SEC = 300                # เงียบเกินกี่วินาทีแล้วลืมบทสนทนาเดิม
RAG_TOP_K = 3                        # ดึงข้อความจากไฟล์ใน knowledge/ มากี่ย่อหน้าให้ LLM เรียบเรียง
RAG_MIN_SCORE = 0.35                 # คะแนนความใกล้เคียงต่ำสุดของย่อหน้าที่จะดึงมา (ต่ำ = ดึงมากขึ้นแต่เพี้ยนง่ายขึ้น)

# =====================================================================
# สลับโมเดลตามความยากของคำถาม
#   คำถามง่าย/สั้น -> โมเดลเร็ว (GROQ_MODELS / GEMINI_MODELS ด้านบน)
#   คำถามยาว/ต้องคิดวิเคราะห์ -> โมเดลฉลาดกว่าด้านล่าง (ช้ากว่าและกินโควต้ามากกว่า) ถ้าล่มจะถอยกลับไปโมเดลเร็วเอง
# =====================================================================
GROQ_SMART_MODELS = ["openai/gpt-oss-120b"]
GEMINI_SMART_MODELS = ["gemini-3.8-flash"]
GROQ_REASONING_FAST = "low"          # ระดับการคิดของ gpt-oss: low / medium / high
GROQ_REASONING_SMART = "medium"
LLM_MAX_TOKENS_SMART = 1500          # รวม token ที่ใช้คิดด้วย
LLM_TIMEOUT_SMART_SEC = 15
SMART_MIN_CHARS = 45                 # คำถามยาวกว่านี้ (ไม่นับช่องว่าง) ถือว่าซับซ้อน

# =====================================================================
# ค้นข้อมูลสด (Gemini + Google Search) ใช้กับตำแหน่งปัจจุบัน ราคา ข่าว ผลแข่ง สภาพอากาศ
# คำเตือน: ถ้าโปรเจกต์ Google ของคุณเปิดการเรียกเก็บเงินไว้ เกินโควต้าฟรีจะมีค่าใช้จ่าย
#          จึงมีเพดานต่อวันให้ (LIVE_SEARCH_DAILY_LIMIT) ตั้งเป็น 0 เพื่อปิดการค้นโดยไม่ต้องแก้ที่อื่น
# =====================================================================
LIVE_SEARCH_ENABLED = False
GEMINI_SEARCH_MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
LIVE_SEARCH_TIMEOUT_SEC = 20
LIVE_SEARCH_DAILY_LIMIT = 100
LIVE_ANSWER_MAX_CHARS = 450          # ตัดคำตอบที่ยาวเกินไปก่อนอ่านออกเสียง
LIVE_SEARCH_USAGE_FILE = os.path.join(BASE_DIR, "live_search_usage.json")