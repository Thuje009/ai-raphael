import os
import ctypes
import re
import time
import sounddevice as sd
import speech_recognition as sr
from gtts import gTTS
from scipy.io.wavfile import write
from config import BASE_DIR, WAKE_DISPLAY, DEBUG_MIC

def play_mp3(path):
    winmm = ctypes.windll.winmm
    alias = "reply_audio"
    winmm.mciSendStringW(f'open "{os.path.abspath(path)}" type mpegvideo alias {alias}', None, 0, None)
    winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
    winmm.mciSendStringW(f"close {alias}", None, 0, None)

def speak(message, say=None):
    print(message)
    text_to_say = say if say is not None else message
    clean = re.sub(r"[^\w\s\u0E00-\u0E7F.,:'\"-]", "", text_to_say).strip()
    if not clean:
        return

    filename = os.path.join(BASE_DIR, "reply.mp3")
    try:
        gTTS(text=clean, lang="th").save(filename)
        play_mp3(filename)
    except Exception as e:
        print(f"⚠️ พูดไม่สำเร็จ: {e}")
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass

def record_and_recognize(prompt_text=None):
    duration, fs = 5, 44100
    filename = os.path.join(BASE_DIR, "temp_audio.wav")

    if prompt_text:
        print(f"\n🎙️ {prompt_text}")
    else:
        print(f"\n🎙️ กำลังสแตนด์บาย... (เรียกชื่อ '{WAKE_DISPLAY}' ก่อนสั่ง)")

    try:
        audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="int16")
        sd.wait()
    except Exception as e:
        print(f"❌ อัดเสียงไม่สำเร็จ: {e}")
        time.sleep(1)
        return ""

    max_volume = int(np.abs(audio_data).max() if 'np' in globals() else abs(audio_data).max())
    if DEBUG_MIC:
        print(f"🎚️ ระดับเสียงสูงสุด: {max_volume}")
    
    if max_volume < 500:
        import numpy as np
        gain = min(8, 12000 / max(max_volume, 1))
        audio_data = np.clip(audio_data.astype(np.float32) * gain, -32768, 32767).astype(np.int16)

    write(filename, fs, audio_data)
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10
    try:
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language="th-TH").lower()
    except Exception:
        return ""
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass