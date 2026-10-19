import ctypes
import mss
import pyautogui

print("=== DPI Awareness ===")

try:
    value = ctypes.c_int()
    ctypes.windll.shcore.GetProcessDpiAwareness(
        None,
        ctypes.byref(value)
    )
    print("DPI Awareness:", value.value)
except Exception as e:
    print("DPI Error:", e)

print("\n=== MSS Monitors ===")

with mss.mss() as sct:
    for i, m in enumerate(sct.monitors):
        print(f"Monitor {i}: {m}")

print("\n=== PyAutoGUI ===")
print("Screen size:", pyautogui.size())
print("Mouse position:", pyautogui.position())

print("\nเลื่อนเมาส์ไปกลางปุ่ม Skip Ad แล้วกด Enter")
input()

print("Actual mouse position:", pyautogui.position())