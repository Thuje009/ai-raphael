import os
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WAKE_WORDS = ("raphael", "rafael", "ราฟาเอล", "ราฟาแอล", "ราฟาเอ็ล", "ราฟา")
WAKE_DISPLAY = "ราฟาเอล"
PREFER_GEMINI = False
DEBUG_MIC = True
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash"]

SKIP_DIR = os.path.join(BASE_DIR, "Image")
SKIP_IMAGE = os.path.join(BASE_DIR, "skip_btn.png")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")

MONITOR_INDEX = 1
SCALES = np.linspace(0.7, 1.5, 7)
REQUIRE_YOUTUBE_FOREGROUND = True
DEBUG_AD_SKIPPER = True
MATCH_THRESHOLD = 0.82
CLICK_COOLDOWN = 3.0