"""ระบบควบคุมหน้าต่างและระบบคอมพิวเตอร์ของราฟาเอล"""
import os
import pygetwindow as gw
import pyautogui
from common import GUI_LOCK
from speech import speak



def close_explorer_windows():
    for w in gw.getAllWindows():
        try:
            if w.title and w.title != "Program Manager" and not w.isMinimized:
                if any(k in w.title.lower() for k in ["file explorer", "this pc", "เดสก์ท็อป", "ดาวน์โหลด", "เอกสาร", "ไดรฟ์", "คลัง", "control panel", "แผงควบคุม"]):
                    w.close()
        except Exception: 
            pass

def close_other_windows():
    excluded = ["visual studio code", "vscode", "cmd.exe", "command prompt", "powershell", "terminal", "raphael"]
    count = sum(1 for w in gw.getAllWindows() if w.title and not w.isMinimized and not any(ex in w.title.lower() for ex in excluded) and (w.close() or True))
    print(f"🧹 ปิดหน้าต่างอื่นไป {count} หน้าต่าง")