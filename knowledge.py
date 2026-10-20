"""
ฐานความรู้ของราฟาเอล ลำดับการหาคำตอบ (เร็ว/ฟรี -> ช้า):
    กฎตายตัว -> cache -> ไฟล์ในโฟลเดอร์ knowledge/ -> Wikipedia (เฉพาะคำถามเชิงข้อเท็จจริง)
ถ้าไม่เจอ ผู้เรียก (assistant.py) จะส่งต่อให้ LLM แล้วเรียก remember() เก็บคำตอบไว้
"""
import datetime
import json
import os
import re
from urllib.parse import quote

import requests

from config import (KNOWLEDGE_DIR, KNOWLEDGE_CACHE_FILE, KNOWLEDGE_CACHE_MAX,
                    FILE_MATCH_THRESHOLD, WIKI_LANG, WIKI_TIMEOUT_SEC, RAG_TOP_K, RAG_MIN_SCORE)

DAYS_TH = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
MONTHS_TH = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]

# ตัดเฉพาะท้ายประโยค/ต้นประโยค กันไปตัดกลางคำ (เช่น "ช่วย" ใน "ช่วยเหลือ", "ที" ใน "สถานที่")
TAIL_FILLERS = r"(ครับ|ค่ะ|คะ|นะครับ|นะคะ|หน่อย|ด้วย)+$"
HEAD_FILLERS = r"^(ช่วยบอก|ช่วยเล่า|ช่วยอธิบาย|ช่วย|ขอ)"
FACT_WORDS = (r"(คือใคร|คืออะไร|คือ|ประวัติ|เกิดเมื่อ|เกิดที่|เสียชีวิต|เล่าเรื่อง|เกี่ยวกับ|"
              r"ความหมายของ|หมายถึง|อธิบาย|ใครคือ|ใครเป็น|เมืองหลวง|ตั้งอยู่|สร้างเมื่อ|"
              r"เมื่อไหร่|เมื่อไร|ปีไหน|ที่ไหน)")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def normalize(q):
    q = re.sub(r"\s+", "", (q or "").lower())
    return re.sub(TAIL_FILLERS, "", q)


def extract_topic(q):
    """ตัดคำถามออก เหลือหัวข้อที่ต้องการค้น เช่น 'ราชวงศ์จักรีคืออะไร' -> 'ราชวงศ์จักรี'"""
    t = re.sub(FACT_WORDS, " ", q.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(TAIL_FILLERS, "", t).strip()
    return re.sub(HEAD_FILLERS, "", t).strip()


def looks_factual(q):
    return re.search(FACT_WORDS, q) is not None


def _grams(s, n=3):
    # ไม่ใช้ \w เพราะสระ/วรรณยุกต์ไทย (Mn) จะถูกมองเป็นตัวที่ไม่ใช่ตัวอักษร
    s = re.sub(r"[\s.,!?;:\"'()\[\]{}\-_/\\]+", "", s.lower())
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def shorten(text, limit=350):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = max(cut.rfind(" "), cut.rfind("."))
    return (cut[:idx] if idx > limit * 0.5 else cut).strip()


# ---------------------------------------------------------------------
# คำถามที่ต้องใช้ "ข้อมูลสด" (ตำแหน่งปัจจุบัน ราคา ข่าว ผลแข่ง ฯลฯ)
# LLM ตอบเรื่องพวกนี้จากความจำแล้วมั่วชื่อ/ตัวเลขได้ จึงตอบตามจริงว่าไม่มีข้อมูลสด แทนการเดา
# (เมื่อมีระบบค้นข้อมูลสดในอนาคต ให้ข้ามตัวตรวจนี้)
# ---------------------------------------------------------------------
LIVE_CUES = r"(ปัจจุบัน|ตอนนี้|ขณะนี้|ล่าสุด|ใหม่ล่าสุด|วันนี้)"
LIVE_TOPICS = (r"(นายก|รัฐมนตรี|ประธานาธิบดี|ผู้ว่า|ซีอีโอ|ceo|ราคา|ข่าว|ผลบอล|ผลการแข่งขัน|ผลแข่ง|"
               r"หุ้น|ค่าเงิน|อัตราแลกเปลี่ยน|อากาศ|ฝนตก|ดัชนี)")
LIVE_DATA_REPLY = ("รายงานค่ะ ข้อมูลนี้เปลี่ยนแปลงตามเวลา ดิฉันยังไม่มีข้อมูลสดจึงไม่ขอเดา "
                   "รบกวนท่านตรวจสอบจากแหล่งข่าวโดยตรงนะคะ")


def needs_live_data(q):
    t = (q or "").lower()
    return bool((re.search(LIVE_CUES, t) and re.search(LIVE_TOPICS, t))
                or re.search(r"(ราคาทอง|ราคาน้ำมัน|ข่าววันนี้|ผลบอลเมื่อคืน)", t))


# ---------------------------------------------------------------------
# 1) กฎตายตัว (ไม่ต้องใช้เน็ต/AI)
# ---------------------------------------------------------------------
def rule_answer(q):
    n = normalize(q)
    now = datetime.datetime.now()

    if re.search(r"(เป็นใคร|แนะนำตัว|(คุณ|เธอ|ตัวเอง)ชื่อ)", n):
        return "ดิฉันชื่อราฟาเอล ผู้ช่วยปัญญาประดิษฐ์สายวิเคราะห์ประจำตัวท่านค่ะ"
    if re.search(r"(ทำอะไรได้บ้าง|ช่วยอะไรได้บ้าง)", n):
        return ("รายงาน ดิฉันควบคุมระบบ Windows เปิดปิดโปรแกรม เปิดเพลง ควบคุมสื่อ "
                "ข้ามโฆษณา YouTube อัตโนมัติ, สแตนด์บายรับคำสั่งผ่าน Telegram Bot, "
                "ตรวจจับและตอบแชท IG ด้วยเสียง, สแกนไวรัสในเบื้องหลังพร้อมรายงานผล, "
                "ตั้งเตือน, จดโน้ต, เช็กสถานะคอมพิวเตอร์ และแปลภาษาได้ค่ะ")
    if len(n) <= 12 and "สวัสดี" in n:
        return "สวัสดีครับ มีอะไรให้ช่วยไหมครับ"
    if len(n) <= 12 and "ขอบคุณ" in n:
        return "ยินดีครับ"
    if re.search(r"เดือน(นี้)?(เดือน)?อะไร", n):
        return f"ตอนนี้เป็นเดือน{MONTHS_TH[now.month - 1]}ครับ"
    if re.search(r"(ปีนี้ปีอะไร|ปีอะไรแล้ว|พ\.?ศ\.?อะไร|ปีนี้พ\.?ศ)", n):
        return f"ตอนนี้เป็นปี พ.ศ. {now.year + 543} หรือ ค.ศ. {now.year} ครับ"
    return None


# ---------------------------------------------------------------------
# 2) Cache คำตอบที่เคยหามาแล้ว
# ---------------------------------------------------------------------
def _load_cache():
    try:
        with open(KNOWLEDGE_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    while len(cache) > KNOWLEDGE_CACHE_MAX:
        cache.pop(next(iter(cache)))          # ทิ้งตัวที่เก่าที่สุด
    try:
        with open(KNOWLEDGE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"⚠️ บันทึก cache ไม่สำเร็จ: {e}")


def remember(q, answer):
    key = normalize(q)
    if not key or not answer:
        return
    cache = _load_cache()
    cache.pop(key, None)
    cache[key] = answer
    _save_cache(cache)


def cache_answer(q):
    return _load_cache().get(normalize(q))


# ---------------------------------------------------------------------
# 3) ค้นจากไฟล์ .txt / .md ในโฟลเดอร์ knowledge/
#    ภาษาไทยไม่มีช่องว่างคั่นคำ จึงเทียบด้วย "ชุดตัวอักษร 3 ตัวติดกัน" แทนการตัดคำ
# ---------------------------------------------------------------------
_index = {"sig": None, "chunks": []}


def _file_signature():
    sig = []
    for root, _dirs, files in os.walk(KNOWLEDGE_DIR):
        for name in files:
            if name.lower().endswith((".txt", ".md")):
                p = os.path.join(root, name)
                try:
                    sig.append((p, os.path.getmtime(p)))
                except OSError:
                    pass
    return tuple(sorted(sig))


def _load_chunks(sig):
    chunks = []
    for path, _mtime in sig:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for para in re.split(r"\n\s*\n", content):
            para = para.strip()
            parts = para.split("\n") if len(para) > 500 else [para]
            for part in parts:
                part = part.strip().lstrip("#").strip()
                if len(part) >= 20:
                    chunks.append((part, _grams(part)))
    return chunks


def retrieve(q, k=None, min_score=None):
    """ดึงย่อหน้าจากไฟล์ใน knowledge/ ที่ใกล้เคียงกับคำถามที่สุด คืน [(ข้อความ, คะแนน 0-1)] เรียงจากมากไปน้อย
    ใช้เป็น "ข้อมูลอ้างอิง" ให้ LLM เรียบเรียงเป็นคำตอบ (RAG) แทนการอ่านย่อหน้าดิบออกเสียง"""
    k = RAG_TOP_K if k is None else k
    min_score = RAG_MIN_SCORE if min_score is None else min_score
    if not os.path.isdir(KNOWLEDGE_DIR):
        return []
    sig = _file_signature()
    if sig != _index["sig"]:
        _index["sig"], _index["chunks"] = sig, _load_chunks(sig)
    if not _index["chunks"]:
        return []

    topic = extract_topic(q)
    if len(topic.replace(" ", "")) < 3:
        return []
    q_grams = _grams(topic)
    if not q_grams:
        return []

    scored = [(len(q_grams & grams) / len(q_grams), text) for text, grams in _index["chunks"]]
    scored = [(text, score) for score, text in sorted(scored, key=lambda x: x[0], reverse=True)[:k]
              if score >= min_score]
    return scored


def file_answer(q):
    if not os.path.isdir(KNOWLEDGE_DIR):
        return None
    sig = _file_signature()
    if sig != _index["sig"]:
        _index["sig"], _index["chunks"] = sig, _load_chunks(sig)
    if not _index["chunks"]:
        return None

    topic = extract_topic(q)
    if len(topic.replace(" ", "")) < 3:
        return None
    q_grams = _grams(topic)
    if not q_grams:
        return None

    best_score, best_text = 0.0, None
    for text, grams in _index["chunks"]:
        score = len(q_grams & grams) / len(q_grams)
        if score > best_score:
            best_score, best_text = score, text
    if best_text and best_score >= FILE_MATCH_THRESHOLD:
        return shorten(best_text)
    return None


# ---------------------------------------------------------------------
# 4) Wikipedia (เฉพาะคำถามที่ดูเป็นข้อเท็จจริง)
# ---------------------------------------------------------------------
WIKI_HEADERS = {"User-Agent": "RaphaelAssistant/1.0 (personal voice assistant project)"}


def wiki_answer(q):
    topic = extract_topic(q)
    if len(topic.replace(" ", "")) < 2:
        return None
    base = f"https://{WIKI_LANG}.wikipedia.org"
    try:
        r = requests.get(f"{base}/w/api.php", headers=WIKI_HEADERS, timeout=WIKI_TIMEOUT_SEC, params={
            "action": "query", "list": "search", "srsearch": topic,
            "format": "json", "srlimit": 1})
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        s = requests.get(f"{base}/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
                         headers=WIKI_HEADERS, timeout=WIKI_TIMEOUT_SEC).json()
    except Exception as e:
        print(f"⚠️ Wikipedia ใช้ไม่ได้: {e}")
        return None

    if s.get("type") == "disambiguation":
        return None
    text = s.get("extract") or ""
    # ตรวจว่าบทความที่เจอเกี่ยวข้องกับหัวข้อจริง (กันได้ผลค้นหาที่ไม่ตรง)
    t_grams = _grams(topic)
    if t_grams and len(t_grams & _grams(title + text[:300])) / len(t_grams) < 0.5:
        return None
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)       # ตัดวงเล็บ (ชื่ออังกฤษ ฯลฯ) ที่อ่านออกเสียงแล้วแปลก
    return shorten(text) or None


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def local_answer(q):
    """หาคำตอบโดยไม่พึ่ง LLM คืน None ถ้าไม่เจอ"""
    a = rule_answer(q)
    if a:
        return a
    a = cache_answer(q)
    if a:
        print("💾 ตอบจาก cache")
        return a
    a = file_answer(q)
    if a:
        print("📚 ตอบจากไฟล์ในโฟลเดอร์ knowledge")
        return a
    if looks_factual(q):
        print("🔎 กำลังค้นหาจาก Wikipedia...")
        a = wiki_answer(q)
        if a:
            remember(q, a)
            return a
    return None