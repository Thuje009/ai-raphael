import os
import time
import threading

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw

from common import GUI_LOCK
from config import (SKIP_DIR, SKIP_IMAGE, IMAGE_EXTS, MONITOR_INDEX, SCALES,
                    REQUIRE_YOUTUBE_FOREGROUND, CROP_TO_WINDOW, DEBUG_AD_SKIPPER,
                    MATCH_THRESHOLD, CLICK_COOLDOWN, CLICK_OFFSET_X, CLICK_OFFSET_Y)

skipper_stop = threading.Event()
skipper_thread = None


def get_target_window():
    """คืน (ทำงานต่อได้ไหม, หน้าต่างที่ active)
    ถ้าไม่บังคับว่า YouTube ต้องอยู่หน้าสุด หรืออ่านหน้าต่างไม่ได้ จะสแกนทั้งจอ"""
    if not REQUIRE_YOUTUBE_FOREGROUND:
        return True, None
    try:
        w = gw.getActiveWindow()
    except Exception:
        return True, None
    if w and w.title and "youtube" in w.title.lower():
        return True, w
    return False, None


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


def capture_region(sct, monitor, win):
    """จับภาพเฉพาะส่วนที่จำเป็น (หน้าต่าง YouTube ∩ จอที่เลือก) คืนภาพเทา + พิกัดมุมซ้ายบนบนจอ"""
    left, top = monitor["left"], monitor["top"]
    right, bottom = left + monitor["width"], top + monitor["height"]
    if win is not None and CROP_TO_WINDOW:
        l, t = max(win.left, left), max(win.top, top)
        r, b = min(win.left + win.width, right), min(win.top + win.height, bottom)
        if r - l >= 100 and b - t >= 100:          # หน้าต่างอยู่คนละจอ/เล็กผิดปกติ -> ใช้ทั้งจอแทน
            left, top, right, bottom = l, t, r, b
    area = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    gray = cv2.cvtColor(np.array(sct.grab(area)), cv2.COLOR_BGRA2GRAY)
    return gray, left, top


def match_templates(roi_gray, templates, hint=None):
    """คืน (คะแนน, ตำแหน่ง, ขนาด, ชื่อ, hint) หยุดทันทีเมื่อเจอที่ผ่านเกณฑ์
    hint = (เทมเพลต, สเกล) ที่เจอครั้งก่อน จะถูกลองก่อนเพื่อความเร็ว"""
    rh, rw = roi_gray.shape[:2]
    order = [(ti, vi) for ti, (_n, variants) in enumerate(templates) for vi in range(len(variants))]
    if hint in order:
        order.remove(hint)
        order.insert(0, hint)

    best = (0.0, None, (0, 0), "", None)
    for ti, vi in order:
        name, variants = templates[ti]
        t, tw, th = variants[vi]
        if th > rh or tw > rw:
            continue
        res = cv2.matchTemplate(roi_gray, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv > best[0]:
            best = (mv, ml, (tw, th), name, (ti, vi))
            if mv >= MATCH_THRESHOLD:
                break
    return best


def auto_skip_ads_loop():
    print("👀 RAPHAEL: เริ่มระบบข้ามโฆษณาแล้วค่ะ")
    templates = load_templates()
    if not templates:
        print(f"❌ ไม่พบรูปปุ่มข้ามโฆษณาใน {SKIP_DIR}")
        return

    last_click_time = 0.0
    last_debug_time = 0.0
    hint = None
    with mss.mss() as sct:
        while not skipper_stop.is_set():
            try:
                ok, win = get_target_window()
                if not ok:
                    skipper_stop.wait(1)
                    continue

                monitor = sct.monitors[MONITOR_INDEX]
                roi, left, top = capture_region(sct, monitor, win)
                best_val, best_loc, best_size, best_name, hint = match_templates(roi, templates, hint)
                now = time.time()

                if DEBUG_AD_SKIPPER and 0.6 <= best_val < MATCH_THRESHOLD and now - last_debug_time > 2:
                    print(f"🔍 AdSkipper: คะแนนสูงสุด {best_val:.2f} ({best_name}) ยังไม่ถึงเกณฑ์ {MATCH_THRESHOLD}")
                    last_debug_time = now

                if best_val >= MATCH_THRESHOLD and best_loc is not None:
                    if now - last_click_time > CLICK_COOLDOWN:
                        tw, th = best_size
                        cx = left + best_loc[0] + tw // 2 + CLICK_OFFSET_X
                        cy = top + best_loc[1] + th // 2 + CLICK_OFFSET_Y

                        print(f"🎯 พบปุ่มข้ามโฆษณา! ({best_name}, {best_val:.2f}) ที่ X:{cx} Y:{cy}")
                        with GUI_LOCK:
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