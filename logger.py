import os
import json
from config import BASE_DIR


LOG_FILE = os.path.join(BASE_DIR, "unknown_commands.json")

def log_unknown_command(text):
    if not text:
        return
    
    data = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []

    # ป้องกันการบันทึกคำสั่งซ้ำติดๆ กัน
    if data and data[-1].get("text") == text:
        return

    from datetime import datetime
    entry = {
        "text": text,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    data.append(entry)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"📝 [Learning System] บันทึกคำสั่งที่ยังไม่เข้าใจลง Log แล้ว: '{text}'")
    except Exception as e:
        print(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")