"""
ชั้น LLM: Groq (หลัก) -> Gemini (สำรอง)
เรียกครั้งเดียวได้ทั้ง "แปลงเป็นคำสั่ง" และ "ตอบคำถาม" ผลลัพธ์เป็น dict:
    {"intent": str, "query": str, "answer": str, "cacheable": bool}
"""
import datetime
import json
import re
import time
from datetime import datetime, timezone

import requests

from persona import PERSONA_PROMPT
from config import (GROQ_API_KEY, GROQ_MODELS, GEMINI_API_KEY, GEMINI_MODELS,
                    LLM_PROVIDERS, LLM_TIMEOUT_SEC, LLM_MAX_TOKENS)

INTENTS = [
    "play_music", "next_music", "prev_music", "pause_music",
    "volume_up", "volume_down", "mute_audio",
    "open_youtube", "close_youtube", "open_notepad", "close_notepad",
    "open_chrome", "close_chrome", "open_calc",
    "get_time", "get_date", "check_specific_date",
    "write_notepad", "save_note",
    "set_reminder", "list_reminders", "cancel_reminders",
    "lock_screen", "close_window",
    "shutdown_pc", "restart_pc", "sleep_pc", "cancel_shutdown",
    "exit_system", "unknown",
]
VALID_INTENTS = set(INTENTS) | {"answer", "unknown"}
VALID = VALID_INTENTS

UNKNOWN = {"intent": "unknown", "query": "", "answer": "", "cacheable": False}

SYSTEM_PROMPT = """{persona}

ตอนนี้คือ {now}
วิเคราะห์ข้อความล่าสุดของผู้ใช้ (โดยดูประวัติการคุยก่อนหน้าประกอบ) แล้วตอบเป็น JSON เท่านั้น รูปแบบ:
{{"intent": "...", "query": "...", "answer": "...", "cacheable": true}}

กติกา:
1. ถ้าเป็นคำสั่งควบคุมคอมพิวเตอร์ ให้ intent เป็นชื่อคำสั่งจากรายการด้านล่าง
   query = ชื่อเพลงหรือข้อความที่ต้องใช้ (ถ้าไม่มีให้เว้นว่าง) และ answer ว่างไว้
   ถ้า intent เป็น set_reminder หรือ cancel_reminders ให้ query = ข้อความเดิมของผู้ใช้ทั้งประโยค
2. ถ้าเป็นคำถามหรือชวนคุย ให้ intent = "answer" และ answer = คำตอบภาษาไทยตามบุคลิกข้างต้น
   กระชับ ไม่เกิน 3 ประโยค ห้ามมี markdown อีโมจิ หรือลิงก์ เพราะจะถูกอ่านออกเสียง
3. cacheable = true เฉพาะคำตอบที่ไม่เปลี่ยนตามเวลาและไม่พึ่งบริบทการคุย (ประวัติศาสตร์ ความรู้ทั่วไป)
   ข้อมูลที่เปลี่ยนได้ (ข่าว ราคา อากาศ ผลกีฬา ตำแหน่งปัจจุบัน) หรือคำตอบที่ใช้ประวัติการคุย ให้ false
4. ถ้าเป็นคำถามแต่ไม่แน่ใจคำตอบ ให้ intent = "answer" แล้วตอบตรงๆ ใน answer ว่ายืนยันไม่ได้ ห้ามเดา
   ใช้ intent = "unknown" เฉพาะเมื่อข้อความไม่ใช่คำสั่งและฟังไม่เป็นประโยค (เสียงรบกวน คำที่ขาดหาย) และเว้น answer ว่าง

รายการ intent: {intents}{context}"""

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


def _history_json(answer):
    """เก็บคำตอบเก่าในรูป JSON เดียวกับที่ต้องการ โมเดลจะได้ตอบเป็น JSON ต่อเนื่องกัน"""
    return json.dumps({"intent": "answer", "query": "", "answer": answer, "cacheable": False},
                        ensure_ascii=False)


def _context_block(chunks):
    if not chunks:
        return ""
    lines = [f"[{i}] {c}" for i, c in enumerate(chunks, 1)]
    return ("\n\nข้อมูลอ้างอิง (จากฐานความรู้ของผู้ใช้หรือสารานุกรม):\n" + "\n".join(lines) +
            "\nวิธีใช้: ถ้าคำถามเกี่ยวกับข้อมูลนี้ ให้เรียบเรียงเป็นคำพูดธรรมชาติตามบุคลิก ไม่ต้องอ่านทวนตามตัวอักษร "
            "และห้ามเพิ่มข้อเท็จจริงเฉพาะเรื่องที่ไม่อยู่ในข้อมูล ถ้าข้อมูลไม่เกี่ยวกับคำถาม ให้ละเลยและตอบตามปกติ")


def _groq_chat(model, system, user, history=()):
    messages = [{"role": "system", "content": system}]
    for u, a in history:
        messages.append({"role": "user", "content": u})
        messages.append({"role": "assistant", "content": _history_json(a)})
    messages.append({"role": "user", "content": user})
    payload = {
        "model": model,
        "messages": messages,
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


def _gemini_chat(model, system, user, history=()):
    from google.genai import types

    def part(role, text):
        return types.Content(role=role, parts=[types.Part(text=text)])

    contents = []
    for u, a in history:
        contents.append(part("user", u))
        contents.append(part("model", _history_json(a)))
    contents.append(part("user", user))
    
    # เปิดใช้งาน Google Search Grounding เพื่อดึงข้อมูลสดเรียลไทม์
    config_args = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "temperature": 0.2,
        "tools": [{"google_search": {}}]  # เพิ่มความสามารถในการค้นหาข้อมูลสด
    }
    
    resp = _get_gemini().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config_args),
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


def _loads(raw):
    """แปลงข้อความจาก LLM เป็น dict (รองรับกรณีมี ```json ครอบ หรือมีข้อความปนมา) ไม่ได้คืน None"""
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
    return data if isinstance(data, dict) else None


def _parse(data):
    """Validate and normalize an LLM response."""
    if isinstance(data, str):
        data = _loads(data)

    if not isinstance(data, dict):
        return None

    intent = data.get("intent", "answer")
    answer = data.get("answer", "")
    cacheable = data.get("cacheable", False)

    # Validate intent
    if not isinstance(intent, str):
        return None

    intent = intent.strip().lower()

    if intent not in VALID_INTENTS:
        return None

    # Normalize answer
    if not isinstance(answer, str):
        answer = str(answer) if answer is not None else ""

    answer = answer.strip()

    # Only accept a real JSON boolean.
    # Avoid bool("false") == True.
    cacheable = cacheable is True

    # Do not cache actions, unknown intents, or empty answers.
    if intent != "answer" or not answer:
        cacheable = False

    return {
        **data,
        "intent": intent,
        "answer": answer,
        "cacheable": cacheable,
    }


def _run_chain(system, text, parser, history=()):
    """ไล่ลอง provider/โมเดลตามลำดับ คืนผลที่ parser แปลงได้ หรือ None ถ้าล้มเหลวทั้งหมด"""
    for provider, models, call in _providers():
        for model in models:
            if _cooldown.get((provider, model), 0) > time.time():
                continue
            try:
                started = time.time()
                raw_resp = call(model, system, text, history)
                data = parser(raw_resp)
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
    return None


def ask(text, history=None, context=None):
    """ส่งข้อความเข้า LLM รอบเดียว คืน dict (เป็น UNKNOWN ถ้าทุกตัวล้มเหลว)
    history = [(ผู้ใช้พูด, ราฟาเอลตอบ), ...] ย้อนหลัง  context = [ข้อความอ้างอิง, ...] สำหรับตอบจากฐานความรู้"""
    if not _providers():
        return dict(UNKNOWN)
    system = SYSTEM_PROMPT.format(
        persona=PERSONA_PROMPT,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        intents=", ".join(INTENTS),
        context=_context_block(context),
    )
    return _run_chain(system, text, _parse, tuple(history or ())) or dict(UNKNOWN)


REMINDER_PROMPT = """แปลงประโยคตั้งเตือนภาษาไทยเป็น JSON เท่านั้น รูปแบบ:
{{"when": "YYYY-MM-DD HH:MM", "message": "..."}}
ตอนนี้คือ {now}
- when = วันเวลาที่ต้องเตือน (24 ชั่วโมง) ถ้าไม่ระบุวันและเวลานั้นผ่านไปแล้ววันนี้ ให้เป็นพรุ่งนี้
- message = สิ่งที่ต้องเตือน ไม่มีคำว่า "เตือน" และไม่มีเวลา
- ถ้าไม่มีเวลาที่ชัดเจน ให้ when เป็นสตริงว่าง
"""


def validate_reminder_datetime(dt_str: str) -> datetime:
    """Validate and parse reminder datetime string."""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt
    except (ValueError, TypeError) as exc:
        raise ValueError(f"รูปแบบวันที่และเวลาไม่ถูกต้อง: {exc}")


def parse_reminder(text):
    """ใช้ LLM แปลงประโยคตั้งเตือนที่ regex อ่านไม่ออก คืน {"when": datetime, "message": str} หรือ None"""
    if not _providers():
        return None
    system = REMINDER_PROMPT.format(now=datetime.now().strftime("%Y-%m-%d %H:%M (%A)"))
    
    def reminder_parser(raw):
        data = _loads(raw)
        if not data or not isinstance(data, dict):
            return None
        when_str = str(data.get("when") or "").strip()
        if not when_str:
            return None
        try:
            when = datetime.strptime(when_str, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                when = datetime.fromisoformat(when_str)
            except ValueError:
                return None
        return {"when": when, "message": str(data.get("message") or "").strip()}

    return _run_chain(system, text, reminder_parser)


def femme(text):
    """แก้คำลงท้ายที่ผิดในข้อความของผู้ช่วย โดยหลีกเลี่ยงการแก้ทั้งข้อความ"""
    if not text:
        return text

    # แก้คำลงท้ายที่พบบ่อยในข้อความทั่วไป
    text = re.sub(r"นะครับ(?=[\s.!?…]|$)", "นะคะ", text)
    text = re.sub(r"ครับ(?=[\s.!?…]|$)", "ค่ะ", text)

    return text


CONFIRMATION_REQUIRED = {
    "shutdown",
    "restart",
    "delete_file",
    "run_shell",
}


def requires_confirmation(intent: str) -> bool:
    return intent in CONFIRMATION_REQUIRED


# ---------------------------------------------------------------------
# รัน `python llm.py` เพื่อทดสอบ key และดูรายชื่อโมเดลที่ใช้ได้จริง
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if GROQ_API_KEY:
        try:
            r = requests.get("[https://api.groq.com/openai/v1/models](https://api.groq.com/openai/v1/models)",
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

    try:
        reminder_dt = validate_reminder_datetime(
            "2027-01-01T09:00:00+07:00"
        )
    except ValueError as exc:
        print(f"ตั้งเตือนไม่สำเร็จ: {exc}")
    else:
        print(f"เวลาที่ตั้งเตือน: {reminder_dt.isoformat()}")