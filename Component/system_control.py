"""ระบบควบคุมหน้าต่างและระบบคอมพิวเตอร์ของราฟาเอล"""
import subprocess
import threading

import pygetwindow as gw

from speech import speak

# pywin32 เป็นตัวเลือก: ถ้ามีจะเช็กชื่อ class ของหน้าต่าง Explorer ได้แม่นกว่าเดาจาก title
# ติดตั้งด้วย: pip install pywin32
try:
    import win32gui
except ImportError:
    win32gui = None

# ---------------------------------------------------------------------------
# หน้าต่าง
# ---------------------------------------------------------------------------

# หน้าต่างที่ห้ามปิดเด็ดขาด (เทียบแบบ lowercase ว่า "มีคำนี้อยู่ใน title")
# หมายเหตุ: Chrome ที่เปิด debug port 9222 ไว้ให้ IG bot ก็ควรอยู่ในรายการนี้
PROTECTED_TITLES = [
    "visual studio code", "vscode", "cmd.exe", "command prompt",
    "powershell", "terminal", "raphael", "program manager",
    "instagram", "youtube",
]

# keyword สำรอง ใช้เฉพาะตอนไม่มี pywin32
EXPLORER_KEYWORDS = [
    "file explorer", "this pc", "เดสก์ท็อป", "ดาวน์โหลด",
    "ไดรฟ์", "control panel", "แผงควบคุม",
]


def _is_explorer_window(w):
    """True ถ้าเป็นหน้าต่าง File Explorer / Control Panel จริง ๆ"""
    if win32gui is not None:
        try:
            cls = win32gui.GetClassName(w._hWnd)
            return cls == "CabinetWClass"
        except Exception:
            return False
    title = (w.title or "").lower()
    return any(k in title for k in EXPLORER_KEYWORDS)


def close_explorer_windows():
    count = 0
    for w in gw.getAllWindows():
        try:
            title = (w.title or "").strip()
            if not title or title == "Program Manager" or w.isMinimized:
                continue
            if _is_explorer_window(w):
                w.close()
                count += 1
        except Exception:
            pass
    print(f"🗂️ ปิดหน้าต่าง Explorer ไป {count} หน้าต่าง")
    return count


def close_other_windows(confirmed=True):
    """ปิดหน้าต่างทั้งหมดที่ไม่อยู่ใน PROTECTED_TITLES

    ถ้าอยากให้ถามยืนยันก่อน ให้เรียก close_other_windows(confirmed=False)
    ราฟาเอลจะถามกลับ แล้วฝั่ง main.py ค่อยเรียก close_other_windows(True) เมื่อผู้ใช้ตอบรับ
    """
    if not confirmed:
        speak("จะปิดหน้าต่างอื่นทั้งหมด งานที่ยังไม่ได้บันทึกอาจหาย ยืนยันไหมคะ")
        return 0

    count = 0
    for w in gw.getAllWindows():
        try:
            title = (w.title or "").strip()
            if not title or w.isMinimized:
                continue
            if any(p in title.lower() for p in PROTECTED_TITLES):
                continue
            w.close()
            count += 1
        except Exception:
            pass
    print(f"🧹 ปิดหน้าต่างอื่นไป {count} หน้าต่าง")
    return count


# ---------------------------------------------------------------------------
# สแกนไวรัส
# ---------------------------------------------------------------------------

_scan_running = threading.Event()

_SCAN_SCRIPT = r"""
$start = Get-Date
Start-MpScan -ScanType QuickScan -ErrorAction Stop
(Get-MpThreatDetection |
    Where-Object { $_.InitialDetectionTime -ge $start } |
    Measure-Object).Count
"""


def _background_scan_and_report():
    """รัน Quick Scan แล้วรายงานเฉพาะภัยที่ตรวจพบ 'หลังเริ่มสแกนรอบนี้'"""
    try:
        print("🛡️ [System] เริ่มสแกนไวรัสในเบื้องหลัง...")
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _SCAN_SCRIPT],
            capture_output=True, text=True, timeout=1800,
        )
        out = res.stdout.strip()
        print(f"🛡️ [System] สแกนเสร็จ returncode={res.returncode} out={out!r} err={res.stderr.strip()[:200]!r}")

        if res.returncode != 0:
            # สาเหตุที่พบบ่อย: ไม่มีสิทธิ์แอดมิน หรือ Defender ถูกปิด/ใช้ antivirus ตัวอื่น
            speak("สแกนไม่สำเร็จค่ะ ลองรันโปรแกรมด้วยสิทธิ์แอดมิน หรือเช็กว่า Windows Defender เปิดอยู่นะคะ")
        elif out.isdigit() and int(out) > 0:
            speak(f"รายงานค่ะ พบภัยคุกคาม {out} รายการ กรุณาตรวจสอบหน้า Windows Security ด่วนค่ะ")
        else:
            speak("รายงานค่ะ สแกนเรียบร้อยแล้ว ไม่พบภัยคุกคามค่ะ")

    except subprocess.TimeoutExpired:
        speak("สแกนใช้เวลานานเกินไปค่ะ ดิฉันหยุดรอแล้ว ลองตรวจสอบใน Windows Security อีกครั้งนะคะ")
    except Exception as e:
        print(f"⚠️ Scan Thread Error: {e}")
        speak("รายงานค่ะ เกิดข้อผิดพลาดในการสแกนไวรัสค่ะ")
    finally:
        _scan_running.clear()


def scan_virus_in_background():
    """เปิดเธรดสแกนเบื้องหลัง ให้ผู้ใช้สั่งงานต่อได้ทันที (กันสแกนซ้อน)"""
    if _scan_running.is_set():
        speak("กำลังสแกนอยู่แล้วค่ะ รอสักครู่นะคะ")
        return
    _scan_running.set()
    speak("รับทราบค่ะ กำลังสแกนไวรัสในเบื้องหลัง ระหว่างนี้ใช้งานต่อได้ปกติ เสร็จแล้วจะรายงานผลให้ค่ะ")
    threading.Thread(target=_background_scan_and_report, daemon=True, name="Raphael-Scan").start()