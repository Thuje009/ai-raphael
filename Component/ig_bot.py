import time
import threading
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from speech import speak, record_and_recognize

# สร้างตัวล็อกสถานะ เพื่อบอกลูปหลักว่าตอนนี้ IG Bot กำลังใช้ไมค์อยู่
IG_BUSY = threading.Event()

def attach_chrome():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    driver = webdriver.Chrome(options=options)
    for h in driver.window_handles:
        driver.switch_to.window(h)
        if "instagram.com" in driver.current_url:
            break
    return driver

STATUS_LINES = {"กำลังใช้งาน", "Active now", "Active"}

def parse_row(text):
    lines = [l.replace("\xa0", " ").replace("\u200b", "").strip() for l in text.split("\n")]
    lines = [l for l in lines if l]
    if "·" not in lines:
        return None
    unread = lines[-1] == "Unread"
    dot = lines.index("·")
    body = [l for l in lines[:dot] if l not in STATUS_LINES]
    if len(body) < 2:
        return None
    name, preview = body[0], " ".join(body[1:])
    return {
        "name": name,
        "preview": preview,
        "time": lines[dot + 1] if dot + 1 < len(lines) else "",
        "unread": unread,
        "mine": preview.startswith(("คุณ:", "คุณส่ง", "You:", "You sent")),
    }

def get_chats(driver):
    chats = []
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
        try:
            c = parse_row(el.get_attribute("innerText") or "")
            if c:
                chats.append(c)
        except Exception:
            continue
    return chats

def send_ig_reply(driver, reply_text):
    try:
        print("⌨️ กำลังพิมพ์ข้อความตอบกลับ...")
        input_box = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][aria-label*='Message']")
        if not input_box:
            input_box = driver.find_elements(By.CSS_SELECTOR, "p.xdj266r")
            
        if input_box:
            box = input_box[0]
            box.click()
            time.sleep(0.5)
            box.send_keys(reply_text)
            time.sleep(0.5)
            box.send_keys(Keys.ENTER)
            print(f"✅ ส่งข้อความสำเร็จ: {reply_text}")
            speak("ส่งข้อความเรียบร้อยแล้วค่ะ")
            time.sleep(2)
        else:
            print("⚠️ ไม่พบช่องพิมพ์ข้อความในหน้า IG")
            speak("ไม่พบช่องพิมพ์ข้อความค่ะ")
    except Exception as e:
        print("Send reply error:", e)
        speak("เกิดข้อผิดพลาดในการส่งข้อความค่ะ")

def run_ig_monitor():
    try:
        driver = attach_chrome()
        if "direct/inbox" not in driver.current_url:
            driver.get("https://www.instagram.com/direct/inbox/")
            time.sleep(4)

        notified = set()
        print("🤖 [System] ราฟาเอลเริ่มสแตนด์บายตรวจจับและถามตอบแชท IG แล้วครับ")

        while True:
            try:
                for c in get_chats(driver):
                    key = (c["name"], c["preview"])
                    if c["unread"] and not c["mine"] and key not in notified:
                        notified.add(key)
                        print(f"📩 IG Message | {c['name']}: {c['preview']}")
                        
                        # ล็อกสถานะไม่ให้ลูปหลักแย่งไมค์
                        IG_BUSY.set()
                        try:
                            announcement = f"มีข้อความอินสตาแกรมจาก {c['name']} ส่งมาว่า {c['preview']}. จะตอบแชทนี้ไหมคะ"
                            speak(announcement)
                            
                            print("🎤 กำลังฟังคำสั่ง (ตอบ / ไม่ตอบ)...")
                            # เรียกแบบไม่มีข้อความ Prompt ซ้อน เพื่ออัดเสียงตรงๆ
                            decision = record_and_recognize()
                            
                            if not decision:
                                print("🔇 ไม่ได้ยินเสียง ข้ามการตอบกลับ")
                                continue
                                
                            print(f"🗣️ คุณตัดสินใจว่า: {decision}")
                            
                            if any(w in decision for w in ["ไม่ตอบ", "ไม่ต้อง", "ข้าม", "ไม่"]):
                                speak("รับทราบค่ะ เงียบสแตนด์บายรอคำสั่งอื่นต่อค่ะ")
                                continue
                                
                            if any(w in decision for w in ["ตอบ", "เอาเลย", "ได้", "จัดไป", "คุย"]):
                                speak("จะให้ตอบว่าอะไรคะ")
                                # เรียกแบบไม่มีข้อความ Prompt ซ้อน
                                user_reply = record_and_recognize()
                                
                                if user_reply and user_reply.strip():
                                    print(f"🗣️ ข้อความที่จะส่ง: {user_reply}")
                                    
                                    chat_buttons = driver.find_elements(By.CSS_SELECTOR, "div[role='button']")
                                    clicked = False
                                    for btn in chat_buttons:
                                        text = btn.get_attribute("innerText") or ""
                                        if c["name"] in text:
                                            driver.execute_script("arguments[0].click();", btn)
                                            clicked = True
                                            time.sleep(2)
                                            break
                                    
                                    if clicked:
                                        send_ig_reply(driver, user_reply)
                                        driver.get("https://www.instagram.com/direct/inbox/")
                                        time.sleep(3)
                                    else:
                                        print("⚠️ หาหน้าแชทของเพื่อนไม่พบเพื่อกดส่ง")
                                        speak("หาหน้าแชทไม่เจอค่ะ")
                                else:
                                    speak("ไม่ได้ยินข้อความที่จะส่ง ยกเลิกค่ะ")
                            else:
                                speak("ไม่เข้าใจคำสั่ง ข้ามการตอบกลับค่ะ")
                        finally:
                            # ปลดล็อกให้ลูปหลักกลับมาทำงานตามปกติ
                            IG_BUSY.clear()
                            
            except Exception as e:
                print("IG Monitor error:", e)
            time.sleep(5)
    except Exception as e:
        print("⚠️ ไม่สามารถเชื่อมต่อ Chrome Debugging สำหรับ IG Bot ได้:", e)
        
def start_ig_bot_thread():
    t = threading.Thread(target=run_ig_monitor, daemon=True)
    t.start()

if __name__ == "__main__":
    run_ig_monitor()