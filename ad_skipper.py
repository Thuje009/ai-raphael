import os
import time
import threading
import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw
from config import (SKIP_DIR, SKIP_IMAGE, IMAGE_EXTS, MONITOR_INDEX, 
                    SCALES, REQUIRE_YOUTUBE_FOREGROUND, DEBUG_AD_SKIPPER, 
                    MATCH_THRESHOLD, CLICK_COOLDOWN)

skipper_stop = threading.Event()
skipper_thread = None

def youtube_is_foreground():
    try:
        w = gw.getActiveWindow()
        return bool(w and w.title and "youtube" in w.title.lower())
    except Exception:
        return True

def list_template_files():
    files = []
    if os.path.isdir(SKIP_DIR):
        files += [os.path.join(SKIP_DIR, n) for n in sorted(os.listdir(SKIP_DIR))
                  if n.lower().endswith(IMAGE_EXTS)]
    if os.path.isfile(SKIP_IMAGE):
        files.append(SKIP_IMAGE)
    return files

def load_templates():
    loaded = []
    for path in list_template_files():
        name = os.path.basename(path)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
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
    best_val, best_loc, best_size, best_name = 0.0, None, (0, 0), ""
    rh, rw = roi_gray.shape[:2]
    for name, variants in templates:
        for t, tw, th in variants:
            if th > rh or tw > rw:
                continue
            res = cv2.matchTemplate(roi_gray, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best_val:
                best_val, best_loc, best_size, best_name = mv, ml, (tw, th), name
    return best_val, best_loc, best_size, best_name

def auto_skip_ads_loop():
    print("👀 RAPHAEL: เริ่มระบบข้ามโฆษณาแล้วค่ะ")
    templates = load_templates()
    if not templates:
        print(f"❌ ไม่พบรูปปุ่มข้ามโฆษณาใน {SKIP_DIR}")
        return

    last_click_time = 0.0
    with mss.mss() as sct:
        while not skipper_stop.is_set():
            try:
                if REQUIRE_YOUTUBE_FOREGROUND and not youtube_is_foreground():
                    skipper_stop.wait(1)
                    continue

                monitor = sct.monitors[MONITOR_INDEX]
                screen_np = np.array(sct.grab(monitor))
                screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_BGRA2GRAY)

                best_val, best_loc, best_size, best_name = match_templates(screen_gray, templates)
                now = time.time()

                if best_val >= MATCH_THRESHOLD and best_loc is not None:
                    if now - last_click_time > CLICK_COOLDOWN:
                        tw, th = best_size
                        cx = best_loc[0] + tw // 2 + monitor["left"]
                        cy = best_loc[1] + th // 2 + monitor["top"]
                        
                        # สามารถปรับ Offset ตรงนี้ได้ทันทีถ้าพิกัดเคลื่อน
                        OFFSET_X = -270
                        OFFSET_Y = -150
                        cx += OFFSET_X
                        cy += OFFSET_Y

                        print(f"🎯 พบปุ่มข้ามโฆษณา! ที่ X:{cx} Y:{cy}")
                        old_pos = pyautogui.position()
                        pyautogui.click(cx, cy)
                        pyautogui.moveTo(old_pos)
                        last_click_time = now
                        print("⏭️ RAPHAEL: กดข้ามโฆษณาแล้ว")

                skipper_stop.wait(0.3)
            except Exception as e:
                print(f"⚠️ AdSkipper Error: {e}")
                skipper_stop.wait(2)

def start_auto_skip_ads():
    global skipper_thread
    if skipper_thread and skipper_thread.is_alive():
        if not skipper_stop.is_set():
            return True
        skipper_thread.join(timeout=3)
    if not list_template_files():
        return False
    skipper_stop.clear()
    skipper_thread = threading.Thread(target=auto_skip_ads_loop, daemon=True, name="Raphael-AdSkipper")
    skipper_thread.start()
    return True

def stop_auto_skip_ads():
    skipper_stop.set()