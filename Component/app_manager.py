"""Discover and control desktop applications without accepting arbitrary shell commands."""
import os
import re
import winreg
from pathlib import Path

import pygetwindow as gw

ALIASES = {
    "เครื่องคิดเลข": "calculator",
    "คำนวณ": "calculator",
    "calc": "calculator",
    "สมุดบันทึก": "notepad",
    "โน้ตแพด": "notepad",
    "ไฟล์เอ็กซ์พลอเรอร์": "file explorer",
    "ตัวจัดการไฟล์": "file explorer",
    "การตั้งค่า": "settings",
    "ตั้งค่า": "settings",
    "โครม": "google chrome",
    "ดิสคอร์ด": "discord",
    # --- เพิ่มคำพ้องเสียงของ CapCut ตรงนี้ ---
    "แคปคัท": "capcut",
    "แคปชั่น": "capcut",
    "แคปครับ": "capcut",
    "cab cut": "capcut",
    "cap cut": "capcut",
    "แคปตัด": "capcut",
    # --- แอปอื่นๆ ---
    "ไลน์": "line",
    "สตรีม": "steam",
    "สตีม": "steam",
}
BUILTINS = {
    'calculator': ('calc.exe', 'Calculator'),
    'notepad': ('notepad.exe', 'Notepad'),
    'file explorer': ('explorer.exe', 'File Explorer'),
    'settings': ('ms-settings:', 'Settings'),
}


def normalize(name):
    return re.sub(r'\s+', ' ', str(name).casefold()).strip()


def canonical(name):
    key = normalize(name)
    return ALIASES.get(key, key)


def _scan_shortcuts(apps):
    """สแกนทางลัด (.lnk) ใน Start Menu และ Desktop ทุกโฟลเดอร์ที่มีอยู่"""
    candidates = [
        ('APPDATA', 'Microsoft/Windows/Start Menu/Programs'),
        ('PROGRAMDATA', 'Microsoft/Windows/Start Menu/Programs'),
        ('USERPROFILE', 'Desktop'),
        ('PUBLIC', 'Desktop'),
    ]
    for env_name, sub in candidates:
        base = os.environ.get(env_name)
        if not base:                       # ไม่มีตัวแปรนี้ ข้าม (กัน Path('') ชี้ไปโฟลเดอร์ปัจจุบัน)
            continue
        root = Path(base) / sub
        if not root.is_dir():
            continue
        try:
            for shortcut in root.rglob('*.lnk'):
                name = normalize(shortcut.stem)
                no_space_name = name.replace(' ', '')       # เก็บทั้งแบบมีและไม่มีเว้นวรรค (cap cut -> capcut)
                if name and name not in apps:
                    apps[name] = (str(shortcut), shortcut.stem)
                if no_space_name and no_space_name not in apps:
                    apps[no_space_name] = (str(shortcut), shortcut.stem)
        except OSError:
            continue


def _scan_app_paths(apps):
    """สแกนโปรแกรมที่ลงทะเบียนไว้ใน Registry (App Paths)"""
    reg_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, reg_path, 0, winreg.KEY_READ | view) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subname = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subname) as sub:
                                target = winreg.QueryValueEx(sub, '')[0].strip('"')
                            if os.path.isfile(target) and target.lower().endswith('.exe'):
                                name = normalize(Path(subname).stem)
                                apps.setdefault(name, (target, Path(subname).stem))
                        except (OSError, ValueError):
                            continue
            except OSError:
                continue


def scan_apps():
    """Return normalized name -> (launch target, display name)."""
    apps = dict(BUILTINS)
    _scan_shortcuts(apps)
    _scan_app_paths(apps)
    return apps


_APPS = None


def refresh_apps():
    global _APPS
    _APPS = scan_apps()
    return _APPS


def installed_apps():
    return _APPS if _APPS is not None else refresh_apps()


def resolve(name):
    key = canonical(name)
    apps = installed_apps()
    if key in apps:
        return apps[key]
    # Do not guess among multiple similar applications.
    matches = [entry for app_name, entry in apps.items() if key and
               (app_name.startswith(key + ' ') or app_name == key)]
    return matches[0] if len(matches) == 1 else None


def open_app(name):
    found = resolve(name)
    if not found:
        return False, 'ไม่พบโปรแกรมหรือพบชื่อที่ไม่ชัดเจน'
    target, display = found
    try:
        os.startfile(target)
        return True, display
    except OSError as exc:
        return False, str(exc)


def close_app(name):
    """Gracefully close uniquely matched titled window; never kill Windows shell/processes."""
    key = canonical(name)
    if not key or key == 'file explorer':
        return False, 'File Explorer ต้องใช้ตัวจัดการหน้าต่างเฉพาะ'
    found = resolve(name)
    if not found:
        return False, 'ไม่พบโปรแกรมในรายการที่สแกน'
    _, display = found
    terms = {key, normalize(display)}
    if key == 'calculator':
        terms.update({'calculator', 'เครื่องคิดเลข'})
    if key == 'settings':
        terms.update({'settings', 'การตั้งค่า'})
    windows = []
    for window in gw.getAllWindows():
        title = normalize(window.title or '')
        if title and title != 'program manager' and any(
            title == term or title.startswith(term + ' -') or title.endswith(' - ' + term)
            for term in terms
        ):
            windows.append(window)
    if not windows:
        return False, 'ไม่พบหน้าต่างที่ตรงกับโปรแกรม'
    if len(windows) != 1:
        return False, 'พบหลายหน้าต่าง กรุณาระบุหน้าต่างให้ชัดเจน'
    try:
        windows[0].close()
        return True, display
    except Exception as exc:
        return False, str(exc)