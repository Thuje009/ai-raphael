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
                    AD_SCAN_MODE, AD_SCAN_INTERVAL_SEC, DEBUG_AD_SKIPPER,
                    MATCH_THRESHOLD, CLICK_COOLDOWN, CLICK_OFFSET_X, CLICK_OFFSET_Y)

BROWSER_NAMES = ("chrome", "edge", "firefox", "brave", "opera")
MIN_AREA_W, MIN_AREA_H = 100, 60          # พื้นที่ที่เล็กกว่านี้ใส่ปุ่มไม่ได้ ข้ามไป

skipper_stop = threading.Event()
skipper_thread = None


def _is_youtube_window(w):
    try:
        title = (w.title or "").lower()
        return "youtube" in title and any(b in title for b in BROWSER_NAMES) and not w.isMinimized
    except Exception:
        return False            # หน้าต่างเพิ่งถูกปิดระหว่างอ่านค่า


_win_cache = {"t": 0.0, "wins": []}


def _youtube_windows():
    # getAllWindows ค่อนข้างหนัก จึงอ่านซ้ำไม่เกินทุก 0.5 วินาที
    now = time.time()
    if now - _win_cache["t"] > 0.5:
        try:
            _win_cache["wins"] = [w for w in gw.getAllWindows() if _is_youtube_window(w)]
        except Exception:
            _win_cache["wins"] = []
        _win_cache["t"] = now
    return _win_cache["wins"]


def get_scan_areas(sct):
    """คืน list ของพื้นที่ที่ต้องสแกน (left, top, right, bottom) เป็นพิกัดสัมบูรณ์บนจอ ตามโหมดใน config
    ภาพที่จับมาคือภาพ "ที่ซ้อนทับแล้วจริงบนจอ" ถ้ามีหน้าต่างอื่นบังปุ่มอยู่ จะไม่เจอปุ่มและไม่คลิก"""
    if AD_SCAN_MODE == "full_screen":
        m = sct.monitors[MONITOR_INDEX]
        return [(m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])]

    if AD_SCAN_MODE == "foreground":
        try:
            w = gw.getActiveWindow()
        except Exception:
            w = None
        wins = [w] if w and _is_youtube_window(w) else []
    else:                                                  # "youtube_windows"
        wins = _youtube_windows()

    v = sct.monitors[0]                                    # จอเสมือนที่รวมทุกจอ (รองรับหลายจอ)
    vl, vt, vr, vb = v["left"], v["top"], v["left"] + v["width"], v["top"] + v["height"]
    areas = []
    for w in wins:
        try:
            l, t = max(w.left, vl), max(w.top, vt)
            r, b = min(w.left + w.width, vr), min(w.top + w.height, vb)
        except Exception:
            continue
        if r - l >= MIN_AREA_W and b - t >= MIN_AREA_H:
            areas.append((l, t, r, b))
    return areas


def grab_gray(sct, l, t, r, b):
    area = {"left": l, "top": t, "width": r - l, "height": b - t}
    return cv2.cvtColor(np.array(sct.grab(area)), cv2.COLOR_BGRA2GRAY)


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
                areas = get_scan_areas(sct)
                if not areas:
                    skipper_stop.wait(1)                   # ไม่มีหน้าต่าง YouTube ให้ดู พักยาวหน่อย
                    continue

                best = (0.0, None, (0, 0), "", None, 0, 0)
                for (l, t, r, b) in areas:
                    roi = grab_gray(sct, l, t, r, b)
                    val, loc, size, name, h = match_templates(roi, templates, hint)
                    if val > best[0]:
                        best = (val, loc, size, name, h, l, t)
                    if val >= MATCH_THRESHOLD:
                        break
                best_val, best_loc, best_size, best_name, new_hint, left, top = best
                hint = new_hint or hint
                now = time.time()

                if DEBUG_AD_SKIPPER and MATCH_THRESHOLD - 0.1 <= best_val < MATCH_THRESHOLD and now - last_debug_time > 2:
                    print(f"🔍 AdSkipper: คะแนนสูงสุด {best_val:.2f} ({best_name}) ยังไม่ถึงเกณฑ์ {MATCH_THRESHOLD}")
                    last_debug_time = now
                if best_val >= MATCH_THRESHOLD and best_loc is not None:
                    if now - last_click_time > CLICK_COOLDOWN:
                        tw, th = best_size
                        
                        # 1. พิกัดกึ่งกลางปุ่มในภาพที่จับมา (Physical Pixel)
                        phys_x = left + best_loc[0] + tw // 2
                        phys_y = top + best_loc[1] + th // 2
                        
                        # 2. แปลงพิกัดตามสเกลจอบน Windows (อัตราส่วน 3456/1920 ≈ 1.25 หรือ 1.5 ตามจริง)
                        # หากอยู่บนจอ 2 (X >= 1920) ให้แปลงสเกลเฉพาะส่วนของจอ 2
                        if phys_x >= 1920:
                            scale_x = 1536 / 1920 # อัตราส่วนความกว้าง Physical / Logical ของจอ 2
                            scale_y = 864 / 1080  # อัตราส่วนความสูง Physical / Logical ของจอ 2
                            
                            cx = int(1920 + (phys_x - 1920) * scale_x) + CLICK_OFFSET_X
                            cy = int(97 + (phys_y - 97) * scale_y) + CLICK_OFFSET_Y
                        else:
                            cx = phys_x + CLICK_OFFSET_X
                            cy = phys_y + CLICK_OFFSET_Y

                        print(f"🎯 พบปุ่มข้ามโฆษณา! ({best_name}, {best_val:.2f}) คำนวณคลิกที่ X:{cx} Y:{cy}")
                        with GUI_LOCK:
                            old_pos = pyautogui.position()
                            pyautogui.click(cx, cy)
                            pyautogui.moveTo(old_pos)
                        last_click_time = now


                skipper_stop.wait(AD_SCAN_INTERVAL_SEC)
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