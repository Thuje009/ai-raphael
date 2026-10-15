"""
ชั้น LLM: Groq (หลัก) -> Gemini (สำรอง)
เรียกครั้งเดียวได้ทั้ง "แปลงเป็นคำสั่ง" และ "ตอบคำถาม" ผลลัพธ์เป็น dict:
    {"intent": str, "query": str, "answer": str, "cacheable": bool}
"""
import datetime
import json
import re
import time

import requests

from config import (GROQ_API_KEY, GROQ_MODELS, GEMINI_API_KEY, GEMINI_MODELS,
                    LLM_PROVIDERS, LLM_TIMEOUT_SEC, LLM_MAX_TOKENS)

INTENTS = [
    "play_music", "next_music", "prev_music", "pause_music",
    "volume_up", "volume_down", "mute_audio",
    "open_youtube", "close_youtube", "open_notepad", "close_notepad",
    "open_chrome", "close_chrome", "open_calc",
    "get_time", "get_date", "check_specific_date",
    "write_notepad", "save_note",
    "lock_screen", "close_window",
    "shutdown_pc", "restart_pc", "sleep_pc", "cancel_shutdown",
    "exit_system", "unknown",
]
VALID = set(INTENTS) | {"answer"}

UNKNOWN = {"intent": "unknown", "query": "", "answer": "", "cacheable": False}

SYSTEM_PROMPT = """คุณคือ "ราฟาเอล" ผู้ช่วยเสียงภาษาไทยบน Windows พูดสุภาพ ลงท้ายด้วย "ครับ"
ตอนนี้คือ {now}
วิเคราะห์ข้อความของผู้ใช้ แล้วตอบเป็น JSON เท่านั้น รูปแบบ:
{{"intent": "...", "query": "...", "answer": "...", "cacheable": true}}

กติกา:
1. ถ้าเป็นคำสั่งควบคุมคอมพิวเตอร์ ให้ intent เป็นชื่อคำสั่งจากรายการด้านล่าง
   query = ชื่อเพลงหรือข้อความที่ต้องใช้ (ถ้าไม่มีให้เว้นว่าง) และ answer ว่างไว้
2. ถ้าเป็นคำถามหรือชวนคุย ให้ intent = "answer" และ answer = คำตอบภาษาไทย
   สั้นไม่เกิน 2 ประโยค ห้ามมี markdown อีโมจิ หรือลิงก์ เพราะจะถูกอ่านออกเสียง
3. cacheable = true เฉพาะคำตอบที่ไม่เปลี่ยนตามเวลา (ประวัติศาสตร์ ความรู้ทั่วไป)
   ข้อมูลที่เปลี่ยนได้ (ข่าว ราคา อากาศ ผลกีฬา ตำแหน่งปัจจุบัน) ให้ false
4. ไม่รู้หรือไม่แน่ใจ ห้ามเดา ให้ intent = "unknown"

รายการ intent: {intents}"""

# (provider, model) -> เวลา (epoch) ที่จะลองใหม่ได้
_cooldown = {}


class LLMError(Exception):
    def __init__(self, status, message, retry_after=None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retry_after = retry_after


# ---------------------------------------------------------------------
# Provider: Groq (OpenAI-compatible REST)
# ---------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_chat(model, system, user):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_completion_tokens": LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"   # คิดน้อยลง = ตอบเร็วขึ้น
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

    r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=LLM_TIMEOUT_SEC)
    if r.status_code == 400 and "reasoning_effort" in payload:
        payload.pop("reasoning_effort")       # โมเดลบางตัวไม่รองรับพารามิเตอร์นี้
        r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=LLM_TIMEOUT_SEC)
    if r.status_code != 200:
        raise LLMError(r.status_code, r.text[:200], r.headers.get("retry-after"))
    return r.json()["choices"][0]["message"].get("content") or ""


# ---------------------------------------------------------------------
# Provider: Gemini
# ---------------------------------------------------------------------
_gemini_client = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai import types
        _gemini_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=int(LLM_TIMEOUT_SEC * 1000)),  # หน่วย ms
        )
    return _gemini_client


def _gemini_chat(model, system, user):
    from google.genai import types
    resp = _get_gemini().models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return resp.text or ""


# ---------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------
def _providers():
    chain = []
    for name in LLM_PROVIDERS:
        if name == "groq" and GROQ_API_KEY:
            chain.append(("groq", GROQ_MODELS, _groq_chat))
        elif name == "gemini" and GEMINI_API_KEY:
            chain.append(("gemini", GEMINI_MODELS, _gemini_chat))
    return chain


def llm_available():
    return bool(_providers())


def _cooldown_seconds(msg, retry_after=None):
    """ตัดสินว่าควรพักโมเดลนี้นานแค่ไหน แทนการแบนถาวรทั้งเซสชัน"""
    low = msg.lower()
    if any(k in low for k in ("404", "not_found", "model_not_found", "decommission", "does not exist")):
        return 6 * 3600, "ไม่พบโมเดลนี้ (ชื่อผิดหรือถูกปลดแล้ว)"
    if any(k in low for k in ("401", "403", "api key", "api_key", "permission", "unauthorized")):
        return 3600, "API key มีปัญหา"
    if "429" in low or "resource_exhausted" in low or "rate limit" in low:
        try:
            wait = max(5, min(float(retry_after), 600))
        except (TypeError, ValueError):
            wait = 60
        return wait, "โควตา/rate limit เต็มชั่วคราว"
    return 15, "ขัดข้องชั่วคราว"


def _parse(raw):
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None

    intent = str(data.get("intent") or "").strip()
    answer = str(data.get("answer") or "").strip()
    query = str(data.get("query") or "").strip()
    if intent not in VALID:
        intent = "answer" if answer else "unknown"
    if intent == "answer" and not answer:
        intent = "unknown"
    return {"intent": intent, "query": query, "answer": answer,
            "cacheable": bool(data.get("cacheable", False))}


def ask(text):
    """ส่งข้อความเข้า LLM รอบเดียว คืน dict (เป็น UNKNOWN ถ้าทุกตัวล้มเหลว)"""
    chain = _providers()
    if not chain:
        return dict(UNKNOWN)

    system = SYSTEM_PROMPT.format(
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        intents=", ".join(INTENTS),
    )

    for provider, models, call in chain:
        for model in models:
            if _cooldown.get((provider, model), 0) > time.time():
                continue
            try:
                started = time.time()
                data = _parse(call(model, system, text))
                if data is None:
                    print(f"⚠️ {provider}:{model} ตอบรูปแบบไม่ถูกต้อง ลองตัวถัดไป")
                    _cooldown[(provider, model)] = time.time() + 15
                    continue
                print(f"🧠 [{provider}:{model}] {time.time() - started:.1f}s")
                return data
            except Exception as e:
                retry_after = getattr(e, "retry_after", None)
                secs, why = _cooldown_seconds(str(e), retry_after)
                _cooldown[(provider, model)] = time.time() + secs
                print(f"⚠️ {provider}:{model} {why} (พัก {int(secs)} วินาที): {str(e)[:100]}")
    return dict(UNKNOWN)


# ---------------------------------------------------------------------
# รัน `python llm.py` เพื่อทดสอบ key และดูรายชื่อโมเดลที่ใช้ได้จริง
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if GROQ_API_KEY:
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, timeout=8)
            ids = sorted(m["id"] for m in r.json().get("data", []))
            print("Groq models:", ", ".join(ids))
        except Exception as e:
            print("Groq: ดึงรายชื่อไม่สำเร็จ", e)
    else:
        print("ยังไม่ได้ตั้ง GROQ_API_KEY")

    if GEMINI_API_KEY:
        try:
            names = sorted(m.name.replace("models/", "") for m in _get_gemini().models.list())
            print("Gemini models:", ", ".join(names))
        except Exception as e:
            print("Gemini: ดึงรายชื่อไม่สำเร็จ", e)
    else:
        print("ยังไม่ได้ตั้ง GEMINI_API_KEY")

    for q in ("ใครเป็นคนสร้างเว็บไซต์ยูทูป", "เพิ่มเสียงหน่อย"):
        print(q, "->", ask(q))