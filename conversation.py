"""
ความจำสนทนาระยะสั้น: เก็บไม่กี่ประโยคล่าสุด ส่งให้ LLM เพื่อให้ตอบต่อเนื่องได้
ไม่ได้เขียนลงไฟล์ ปิดโปรแกรมแล้วหาย และลืมเองเมื่อเงียบเกิน MEMORY_IDLE_SEC
"""
import re
import time
from collections import deque

from config import MEMORY_TURNS, MEMORY_IDLE_SEC

_turns = deque(maxlen=MEMORY_TURNS)       # (ผู้ใช้พูด, ราฟาเอลตอบ, เวลา)

FOLLOWUP_STARTS = ("แล้ว", "ส่วน", "งั้น", "ต่อ", "อีก", "และ", "แต่")
FOLLOWUP_WORDS = ("เขา", "เธอ", "มัน", "นั่น", "นี่", "นั้น", "เรื่องนั้น", "คนนั้น", "อันนั้น", "ที่นั่น",
                  "ตรงนั้น", "เมื่อกี้", "ที่พูด", "ข้างต้น", "ดังกล่าว")


def add(user_text, answer):
    if user_text and answer:
        _turns.append((user_text, answer, time.time()))


def clear():
    _turns.clear()


def recent():
    """คืน [(ผู้ใช้พูด, ราฟาเอลตอบ), ...] ถ้าเงียบเกินเวลาที่กำหนดจะล้างความจำก่อน"""
    if _turns and time.time() - _turns[-1][2] > MEMORY_IDLE_SEC:
        _turns.clear()
    return [(u, a) for u, a, _t in _turns]


def is_followup(text):
    """เดาว่าเป็นคำถามต่อเนื่องที่ต้องพึ่งบริบทหรือไม่ (ถ้าใช่ จะไม่ค้น cache/ไฟล์/Wikipedia ด้วยข้อความดิบ)"""
    if not recent():
        return False
    t = re.sub(r"\s+", "", text or "")
    return t.startswith(FOLLOWUP_STARTS) or any(w in t for w in FOLLOWUP_WORDS) or len(t) <= 8