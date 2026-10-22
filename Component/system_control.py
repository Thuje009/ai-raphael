"""ระบบควบคุมหน้าต่าง สแกนไวรัส และ git ของราฟาเอล"""
import json
import os
import re
import subprocess
import threading
from datetime import datetime

import pygetwindow as gw

from speech import speak

# pywin32 เป็นตัวเลือก: ถ้ามีจะเช็กชื่อ class ของหน้าต่าง Explorer ได้แม่นกว่าเดาจาก title
# ติดตั้งด้วย: pip install pywin32
try:
    import win32gui
except ImportError:
    win32gui = None

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE) if os.path.basename(_HERE).lower() == "component" else _HERE
CONFIG_PATH = os.path.join(ROOT, "config.json")

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


def dev_window_active():
    """True ถ้าหน้าต่างบนสุดคือ VS Code / terminal (ใช้ช่วยตีความคำสั่ง git ที่ STT ฟังเพี้ยน)"""
    try:
        w = gw.getActiveWindow()
        title = ((w.title or "") if w else "").lower()
    except Exception:
        return False
    return any(k in title for k in ("visual studio code", "cmd.exe", "powershell", "terminal", "raphael", "github"))


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


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
GIT_TIMEOUT = 60

# ไฟล์ที่ห้าม commit อัตโนมัติ ถ้าเจอใน git status (คือไม่ถูก .gitignore กัน) ให้หยุดและบอกผู้ใช้
SENSITIVE = re.compile(
    r"(^|/)(\.env[^/]*|config\.json|id_rsa[^/]*|[^/]*\.(pem|key|p12|pfx)|[^/]*(token|secret|password)[^/]*)$",
    re.IGNORECASE,
)


def _git(args, cwd, timeout=GIT_TIMEOUT):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")      # ห้ามรอถามรหัสผ่าน (ไม่งั้นค้าง)
    return subprocess.run(
        ["git", "-c", "core.quotepath=false"] + args,
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env,
    )
 
 
def _config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
 
 
def _is_repo(path):
    try:
        return os.path.isdir(path) and _git(["rev-parse", "--is-inside-work-tree"], path, 10).returncode == 0
    except Exception:
        return False
 
 
def resolve_project(text=""):
    """คืน (ชื่อ, path) หรือ (None, None)"""
    cfg = _config()
    projects = {k: v for k, v in (cfg.get("projects") or {}).items() if v}
    low = (text or "").lower()
 
    for name, path in projects.items():                       # 1) พูดชื่อมา
        if name.lower() in low:
            return name, path
 
    if projects:                                       # 2) VS Code ที่เปิดอยู่
        try:
            win = gw.getActiveWindow()
            title = (win.title or "") if win else ""
        except Exception:
            title = ""
        if "visual studio code" in title.lower():
            parts = [p.strip().lower() for p in title.split(" - ")]
            for name, path in projects.items():
                if os.path.basename(path.rstrip("\\/")).lower() in parts or name.lower() in parts:
                    return name, path
 
    default = cfg.get("default_project")                      # 3) ค่าเริ่มต้น
    if default in projects:
        return default, projects[default]
    return os.path.basename(ROOT), ROOT                       # 4) ราฟาเอลเอง
 
 
def _changes(cwd):
    """คืนรายชื่อไฟล์ที่เปลี่ยน/ใหม่ (ไม่รวมไฟล์ที่ .gitignore กัน)"""
    out = _git(["status", "--porcelain", "-uall"], cwd).stdout
    files = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:                                    # rename
            path = path.split(" -> ")[-1]
        files.append(path)
    return files
 
 
def _say(msg):
    print(f"🔧 [git] {msg}")
    speak(msg)
    return msg
 
 
def _prepare(text):
    name, path = resolve_project(text)
    if not _is_repo(path):
        _say(f"โฟลเดอร์ {name} ยังไม่ใช่โปรเจกต์ git หรือหาไม่เจอค่ะ ตรวจ projects ใน config.json นะคะ")
        return None, None
    return name, path
 
 
# ---------------------------------------------------------------------
# คำสั่ง
# ---------------------------------------------------------------------
def _current_branch(path):
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], path).stdout.strip()


def _protected_note(path):
    """ถ้าอยู่บน branch หลัก (main/master หรือตาม protected_branches ใน config.json) ให้เตือนในคำถามยืนยัน"""
    protected = _config().get("protected_branches") or ["main", "master"]
    cur = _current_branch(path)
    return f" (ตอนนี้อยู่บน {cur} ซึ่งเป็น branch หลัก)" if cur in protected else ""


def _remote(path):
    remotes = _git(["remote"], path).stdout.split()
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else None


def cmd_status(text=""):
    name, path = _prepare(text)
    if not path:
        return
    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], path).stdout.strip() or "ไม่ทราบ"
        n = len(_changes(path))
        ahead = _git(["rev-list", "--count", "@{u}..HEAD"], path)
        ahead_n = int(ahead.stdout.strip()) if ahead.returncode == 0 and ahead.stdout.strip().isdigit() else None
    except subprocess.TimeoutExpired:
        return _say("git ตอบช้าเกินไปค่ะ ลองใหม่อีกครั้งนะคะ")
 
    msg = f"โปรเจกต์ {name} อยู่ที่ branch {branch} "
    msg += f"มีไฟล์เปลี่ยน {n} ไฟล์ค่ะ" if n else "ไม่มีไฟล์ที่ยังไม่ commit ค่ะ"
    if ahead_n:
        msg += f" และมี {ahead_n} commit ที่ยังไม่ได้ push"
    _say(msg)
 
 
def _message_from(text, n_files):
    m = re.search(r"(?:ข้อความ|ว่า|message)\s*(.+)$", text or "", re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()[:100]
    return f"update: {n_files} files ({datetime.now():%Y-%m-%d %H:%M})"
 
 
def _do_commit(text="", confirm=None, quiet=False):
    """commit ทุกไฟล์ที่เปลี่ยน (ไม่ push) คืน True ถ้า commit สำเร็จ"""
    name, path = _prepare(text)
    if not path:
        return False
    try:
        files = _changes(path)
        if not files:
            _say(f"โปรเจกต์ {name} ไม่มีไฟล์เปลี่ยนแปลงให้ commit ค่ะ")
            return False
 
        risky = [f for f in files if SENSITIVE.search(f.replace("\\", "/"))]
        if risky:
            _say(f"หยุดก่อนค่ะ พบไฟล์ที่อาจเป็นความลับ {', '.join(os.path.basename(r) for r in risky[:3])} "
                 "ที่ยังไม่ได้ใส่ใน gitignore ไม่ commit ให้ ตรวจแล้วสั่งใหม่นะคะ")
            return False
 
        message = _message_from(text, len(files))
        if confirm and not confirm(f"โปรเจกต์ {name} มี {len(files)} ไฟล์เปลี่ยน จะ commit ด้วยข้อความ {message} ใช่ไหมคะ" + _protected_note(path)):
            _say("ยกเลิกการ commit ค่ะ")
            return False
 
        add = _git(["add", "-A"], path)
        if add.returncode != 0:
            _say("เพิ่มไฟล์เข้า git ไม่สำเร็จค่ะ ดูรายละเอียดในหน้าจอ")
            print(add.stderr)
            return False
 
        res = _git(["commit", "-m", message], path)
        if res.returncode != 0:
            err = (res.stderr + res.stdout).lower()
            print(res.stderr or res.stdout)
            if "user.name" in err or "user.email" in err or "tell me who you are" in err:
                _say("git ยังไม่ได้ตั้งชื่อและอีเมลผู้ใช้ค่ะ ต้องตั้ง user.name กับ user.email ก่อน")
            else:
                _say("commit ไม่สำเร็จค่ะ ดูรายละเอียดในหน้าจอ")
            return False
 
        if not quiet:
            _say(f"commit โปรเจกต์ {name} เรียบร้อยแล้วค่ะ {len(files)} ไฟล์")
        return True
    except subprocess.TimeoutExpired:
        _say("git ตอบช้าเกินไปค่ะ ลองใหม่อีกครั้งนะคะ")
        return False
 
 
def _do_push(text="", confirm=None):
    name, path = _prepare(text)
    if not path:
        return False
    try:
        branch = _current_branch(path)
        has_upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], path).returncode == 0
        args = ["push"]
        first_time = ""
        if not has_upstream:
            remote = _remote(path)
            if not remote:
                _say("โปรเจกต์นี้ยังไม่ได้เชื่อมกับ GitHub ค่ะ ต้องเพิ่ม remote เองก่อน")
                return False
            args = ["push", "-u", remote, branch]
            first_time = " (ครั้งแรกของ branch นี้ จะสร้างบน GitHub ให้ด้วย)"
        spoken = branch.replace("/", " ")
        if confirm and not confirm(f"จะ push โปรเจกต์ {name} branch {spoken} ขึ้น GitHub{first_time} ใช่ไหมคะ" + _protected_note(path)):
            _say("ยกเลิกการ push ค่ะ")
            return False

        res = _git(args, path)
        if res.returncode == 0:
            _say(f"push โปรเจกต์ {name} ขึ้น GitHub เรียบร้อยแล้วค่ะ")
            return True
 
        err = (res.stderr + res.stdout).lower()
        print(res.stderr or res.stdout)
        if "no upstream" in err or "set-upstream" in err:
            _say("branch นี้ยังไม่เคยผูกกับ GitHub ค่ะ ต้องพิมพ์ git push -u origin เองครั้งแรก")
        elif "rejected" in err or "non-fast-forward" in err or "fetch first" in err:
            _say("GitHub ปฏิเสธค่ะ เพราะมีการเปลี่ยนแปลงฝั่งนั้นที่เรายังไม่มี ต้อง pull ก่อน")
        elif "authentication" in err or "could not read" in err or "permission" in err or "403" in err:
            _say("ยืนยันตัวตนกับ GitHub ไม่ผ่านค่ะ ตรวจ token หรือ credential ของ git")
        else:
            _say("push ไม่สำเร็จค่ะ ดูรายละเอียดในหน้าจอ")
        return False
    except subprocess.TimeoutExpired:
        _say("push ใช้เวลานานเกินไปค่ะ ตรวจอินเทอร์เน็ตหรือ credential แล้วลองใหม่")
        return False
 
 
def cmd_commit(text="", confirm=None):
    """commit ทุกไฟล์ที่เปลี่ยน (ไม่ push) ไม่คืนค่า เพื่อไม่ให้ตัวจัดการคำสั่งตีความว่า True = ปิดระบบ"""
    _do_commit(text, confirm)


def cmd_push(text="", confirm=None):
    _do_push(text, confirm)


def cmd_commit_push(text="", confirm=None):
    """commit แล้ว push ต่อ (ถามยืนยันแยกกัน และไม่ push ถ้า commit ไม่สำเร็จ)"""
    if _do_commit(text, confirm, quiet=True):
        _do_push(text, confirm)


def _branch_name(text, path):
    """ตั้งชื่ออัตโนมัติ ไม่พึ่งการฟังชื่อไทย:
    - ใช้เฉพาะตัวอักษรอังกฤษ/ตัวเลขจากที่พูดหลังคำว่า "ชื่อ"/"ว่า" (ภาษาไทยทิ้ง)
    - ไม่มีชื่อ -> ใช้วันที่เวลา เช่น feature/20261021-1530
    - ขึ้นต้น fix/ ถ้าพูดถึง fix/bug/บั๊ก ไม่งั้น feature/"""
    low = (text or "").lower()
    prefix = "fix" if re.search(r"(?<![a-z])(fix|bug|hotfix)(?![a-z])|บั๊ก|บัค", low) else "feature"
    m = re.search(r"(?:ชื่อ|ว่า|named|name)\s*(.+)$", low)
    slug = re.sub(r"[^a-z0-9]+", "-", m.group(1)).strip("-")[:30] if m else ""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = f"{prefix}/{slug or stamp}"
    if _git(["check-ref-format", "--branch", base], path).returncode != 0:
        base = f"{prefix}/{stamp}"

    name, n = base, 2
    while _git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], path).returncode == 0:
        name, n = f"{base}-{n}", n + 1                      # ชื่อซ้ำ -> ต่อท้าย -2, -3
    return name


def cmd_new_branch(text="", confirm=None):
    """สร้าง branch ใหม่จาก branch ปัจจุบันแล้วสลับไปเลย (ไฟล์ที่แก้ค้างอยู่ติดไปด้วย)"""
    name, path = _prepare(text)
    if not path:
        return
    try:
        cur = _current_branch(path)
        if cur == "HEAD":
            _say("ตอนนี้ไม่ได้อยู่บน branch ไหนค่ะ (detached HEAD) ให้สลับกลับไปที่ branch ก่อน")
            return

        branch = _branch_name(text, path)
        n = len(_changes(path))
        spoken = branch.replace("/", " ")
        prompt = f"จะสร้าง branch {spoken} จาก {cur} ในโปรเจกต์ {name} ใช่ไหมคะ"
        if n:
            prompt += f" ไฟล์ที่แก้ค้างอยู่ {n} ไฟล์จะติดไปด้วย"
        print(f"🌿 [git] ชื่อ branch ที่จะสร้าง: {branch}")
        if confirm and not confirm(prompt):
            _say("ยกเลิกการสร้าง branch ค่ะ")
            return

        res = _git(["checkout", "-b", branch], path)
        if res.returncode != 0:
            print(res.stderr or res.stdout)
            _say("สร้าง branch ไม่สำเร็จค่ะ ดูรายละเอียดในหน้าจอ")
            return
        print(f"🌿 [git] ตอนนี้อยู่ที่ {branch}  (อยากเปลี่ยนชื่อ: git branch -m ชื่อใหม่)")
        _say(f"สร้าง branch {spoken} และสลับไปแล้วค่ะ")
    except subprocess.TimeoutExpired:
        _say("git ตอบช้าเกินไปค่ะ ลองใหม่อีกครั้งนะคะ")