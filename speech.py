import asyncio
import collections
import ctypes
import hashlib
import os
import re
import time

import numpy as np
import sounddevice as sd
import speech_recognition as sr
from scipy.io.wavfile import write

try:
    from gtts import gTTS    # pip install gTTS
except ImportError:
    gTTS = None

try:
    import edge_tts          # pip install edge-tts (ใช้เมื่อตั้ง TTS_ENGINE = "edge")
except ImportError:
    edge_tts = None

from config import (BASE_DIR, WAKE_DISPLAY, DEBUG_MIC, TTS_ENGINE, TTS_VOICE, TTS_CACHE_DIR,
                    TTS_CACHE_MAX_CHARS, TTS_RATE, TTS_PITCH, MIC_SAMPLE_RATE, VAD_MIN_RMS, VAD_NOISE_RATIO,
                    VAD_SILENCE_SEC, VAD_MAX_WAIT_SEC, VAD_MAX_SEC)


# =====================================================================
# Text-to-Speech
# =====================================================================
def play_mp3(path):
    winmm = ctypes.windll.winmm
    alias = "reply_audio"
    winmm.mciSendStringW(f'open "{os.path.abspath(path)}" type mpegvideo alias {alias}', None, 0, None)
    winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
    winmm.mciSendStringW(f"close {alias}", None, 0, None)


def _cache_path(text):
    # cache ผูกกับเครื่องมือและค่าเสียง เปลี่ยนแล้วไม่ต้องลบไฟล์เก่า
    key = hashlib.md5(f"{TTS_ENGINE}|{TTS_VOICE}|{TTS_RATE}|{TTS_PITCH}|{text}".encode("utf-8")).hexdigest()
    return os.path.join(TTS_CACHE_DIR, key + ".mp3")


def _synth_gtts(text, tmp):
    if gTTS is None:
        raise RuntimeError("ยังไม่ได้ติดตั้ง gTTS (pip install gTTS)")
    gTTS(text=text, lang="th").save(tmp)


def _synth_edge(text, tmp):
    if edge_tts is None:
        raise RuntimeError("ยังไม่ได้ติดตั้ง edge-tts (pip install edge-tts)")
    asyncio.run(edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH).save(tmp))


def _get_audio(text):
    """คืน path ไฟล์เสียงจากเครื่องมือที่เลือกใน TTS_ENGINE เท่านั้น (เสียงเดียวตลอด)
    ล้มเหลวจะลองซ้ำ ไม่สลับไปเสียงอื่น"""
    path = _cache_path(text)
    if os.path.exists(path):
        return path

    synth = _synth_edge if TTS_ENGINE == "edge" else _synth_gtts
    last_error = None
    for _attempt in range(3):
        try:
            tmp = path + ".part"
            synth(text, tmp)
            os.replace(tmp, path)
            return path
        except Exception as e:
            last_error = e
            time.sleep(0.5)
    raise RuntimeError(f"สร้างเสียงด้วย {TTS_ENGINE} ไม่สำเร็จ (เช็กอินเทอร์เน็ต): {last_error}")


def speak(message, say=None):
    print(message)
    text_to_say = say if say is not None else message
    clean = re.sub(r"[^\w\s\u0E00-\u0E7F.,:'\"-]", "", text_to_say).strip()
    if not clean:
        return

    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    path = None
    try:
        path = _get_audio(clean)
        play_mp3(path)
    except Exception as e:
        print(f"⚠️ พูดไม่สำเร็จ: {e}")
    finally:
        # ประโยคสั้น (ที่ใช้ซ้ำบ่อย) เก็บไว้ ส่วนประโยคยาว (คำตอบ) ลบทิ้ง
        if path and len(clean) > TTS_CACHE_MAX_CHARS:
            for p in (path, path + ".part"):
                try:
                    os.remove(p)
                except OSError:
                    pass


# =====================================================================
# Speech-to-Text (หยุดอัดอัตโนมัติเมื่อพูดจบ)
# =====================================================================
_noise = {"rms": None}   # ระดับเสียงรบกวนพื้นหลัง จำไว้ข้ามรอบ


def _rms(block):
    x = block.astype(np.float32)
    return float(np.sqrt(np.mean(x * x)))


def _record_until_silence():
    """คืน array ของเสียงที่อัดได้ หรือ None ถ้าไม่มีใครพูดภายในเวลาที่รอ"""
    fs = MIC_SAMPLE_RATE
    block_len = int(fs * 0.1)                       # บล็อกละ 0.1 วินาที
    silence_blocks_needed = max(1, int(VAD_SILENCE_SEC / 0.1))
    preroll = collections.deque(maxlen=3)           # เก็บเสียง 0.3 วิก่อนเริ่มพูด กันพยางค์แรกขาด
    frames = []
    started = False
    silent_blocks = 0
    speech_start = 0.0
    t0 = time.time()

    with sd.InputStream(samplerate=fs, channels=1, dtype="int16", blocksize=block_len) as stream:
        if _noise["rms"] is None:                   # รอบแรก: วัดเสียงรบกวนจาก 0.3 วินาทีแรก
            _noise["rms"] = min(_rms(stream.read(block_len)[0]) for _ in range(3))

        while True:
            block, _overflow = stream.read(block_len)
            level = _rms(block)
            threshold = max(VAD_MIN_RMS, _noise["rms"] * VAD_NOISE_RATIO)
            now = time.time()

            if not started:
                if level >= threshold:
                    started, speech_start = True, now
                    frames.extend(preroll)
                    frames.append(block)
                else:
                    _noise["rms"] = 0.95 * _noise["rms"] + 0.05 * level
                    preroll.append(block)
                    if now - t0 > VAD_MAX_WAIT_SEC:
                        return None
            else:
                frames.append(block)
                silent_blocks = silent_blocks + 1 if level < threshold else 0
                if silent_blocks >= silence_blocks_needed or now - speech_start > VAD_MAX_SEC:
                    break

    return np.concatenate(frames, axis=0)


def record_and_recognize(prompt_text=None):
    filename = os.path.join(BASE_DIR, "temp_audio.wav")

    if prompt_text:
        print(f"\n🎙️ {prompt_text}")
    else:
        print(f"\n🎙️ กำลังสแตนด์บาย... (เรียกชื่อ '{WAKE_DISPLAY}' ก่อนสั่ง)")

    try:
        audio_data = _record_until_silence()
    except Exception as e:
        print(f"❌ อัดเสียงไม่สำเร็จ: {e}")
        time.sleep(1)
        return ""

    if audio_data is None:
        if DEBUG_MIC:
            print("🔇 ไม่ได้ยินเสียงพูด")
        return ""

    peak = int(np.abs(audio_data.astype(np.int32)).max())
    if DEBUG_MIC:
        print(f"🎚️ ระดับเสียงสูงสุด: {peak}  (ความยาว {len(audio_data) / MIC_SAMPLE_RATE:.1f} วินาที)")

    if peak < 500:                                  # ไมค์เบา: ขยายสัญญาณ
        gain = min(8, 12000 / max(peak, 1))
        audio_data = np.clip(audio_data.astype(np.float32) * gain, -32768, 32767).astype(np.int16)

    write(filename, MIC_SAMPLE_RATE, audio_data)
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10
    try:
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language="th-TH").lower()
    except sr.UnknownValueError:
        return ""                                   # ฟังไม่ออก เป็นเรื่องปกติ
    except Exception as e:
        print(f"⚠️ แปลงเสียงเป็นข้อความไม่สำเร็จ: {e}")
        return ""
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass