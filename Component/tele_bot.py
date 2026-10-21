"""ระบบควบคุมราฟาเอลผ่าน Telegram Bot บนโทรศัพท์มือถือ"""
import os
import psutil
import threading
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import subprocess
import yt_dlp

# พยายามดึงฟังก์ชันจาก app_manager ถ้ามี
try:
    from Component.app_manager import open_application, close_application
except ImportError:
    try:
        from app_manager import open_application, close_application
    except ImportError:
        open_application = None
        close_application = None

# ปิด Log รบกวนจาก Telegram library
logging.getLogger("httpx").setLevel(logging.WARNING)

# ฟังก์ชันช่วยเปิด URL ด้วย Chrome โดยเฉพาะ (ไม่เปิด Edge)
def open_with_chrome(url: str):
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
    ]
    
    launched = False
    for path in chrome_paths:
        if os.path.exists(path):
            try:
                # ใช้ subprocess สั่งรันไฟล์ chrome.exe ตรงๆ พร้อมส่ง URL ไปด้วย
                subprocess.Popen([path, url])
                launched = True
                break
            except Exception:
                continue
                
    # ถ้าหา Chrome ไม่เจอในเครื่องจริงๆ ค่อยเปิดผ่าน Default Browser ปกติ
    if not launched:
        os.system(f'start {url}')

# ฟังก์ชันแสดงช่วยเหลือ (/help และ /start)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    msg = (
        f"🤖 **ราฟาเอล Telegram Remote พร้อมใช้งานค่ะ**\n\n"
        f"🔑 **Chat ID ของท่านคือ:** `{chat_id}`\n\n"
        f"📋 **คำสั่งที่ใช้งานได้:**\n"
        f"• `/open [ชื่อแอป/youtube]` - สั่งเปิดโปรแกรมหรือเว็บ (ผ่าน Chrome)\n"
        f"• `/close [ชื่อแอป/chrome]` - สั่งปิดโปรแกรม\n"
        f"• `/play [ชื่อเพลง]` - สั่งเปิดเพลงผ่าน Chrome / YouTube ทันที\n"
        f"• `/status` - เช็กสถานะ CPU/RAM เครื่อง\n"
        f"• `/shutdown` - สั่งปิดคอมพิวเตอร์\n"
        f"• `/cancel_shutdown` - ยกเลิกการปิดคอมพิวเตอร์\n"
        f"• `/help` - ดูคู่มือคำสั่งทั้งหมด"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ฟังก์ชันสั่งเปิดโปรแกรมหรือ YouTube (บังคับผ่าน Chrome)
async def open_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ กรุณาระบุชื่อโปรแกรมหรือสิ่งที่ต้องการเปิดด้วยค่ะ เช่น `/open youtube`", parse_mode="Markdown")
        return
    
    target = " ".join(context.args).lower()
    
    # กรณีสั่งเปิด YouTube ให้บังคับเปิดผ่าน Chrome เท่านั้น
    if "youtube" in target:
        await update.message.reply_text("🚀 กำลังเปิด YouTube ผ่าน Google Chrome ให้แล้วค่ะ...")
        open_with_chrome("https://www.youtube.com")
        return

    await update.message.reply_text(f"🚀 กำลังสั่งเปิด {target} บนคอมพิวเตอร์ให้แล้วค่ะ...")
    if open_application:
        open_application(target)
    else:
        os.system(f"start {target}")

# ฟังก์ชันสั่งปิดโปรแกรม (รองรับ Chrome)
async def close_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ กรุณาระบุชื่อโปรแกรมที่ต้องการปิดด้วยค่ะ เช่น `/close chrome`")
        return
        
    app_name = context.args[0].lower()
    await update.message.reply_text(f"🛑 กำลังสั่งปิด {app_name} บนคอมพิวเตอร์ให้แล้วค่ะ...")
    
    if "chrome" in app_name:
        os.system("taskkill /f /im chrome.exe >nul 2>&1")
    elif close_application:
        close_application(app_name)
    else:
        os.system(f"taskkill /f /im {app_name}.exe >nul 2>&1")

# ฟังก์ชันสั่งเล่นเพลง (ค้นหาและกดเล่นวิดีโอตัวแรกให้อัตโนมัติทันทีผ่าน Chrome)
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ กรุณาระบุชื่อเพลงด้วยค่ะ เช่น `/play เปี๊ยกปูน` หรือ `/play lo-fi`", parse_mode="Markdown")
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🎵 กำลังค้นหาและเล่นเพลง '{query}' ผ่าน Google Chrome ให้แล้วค่ะ...")
    
    # ใช้ yt-dlp ค้นหาและดึงลิงก์วิดีโอตัวแรกสุดจาก YouTube โดยตรง
    def get_first_youtube_url(search_query):
            ydl_opts = {
                'noplaylist': True,
                'quiet': True,
                'default_search': 'ytsearch1',
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                    if 'entries' in info and len(info['entries']) > 0:
                        video_id = info['entries'][0]['id']
                        return f"https://www.youtube.com/watch?v={video_id}"
            except Exception as e:
                print(f"Error fetching YouTube link: {e}")
            
            return f"https://www.youtube.com/results?search_query={search_query}"

    # ดึงลิงก์วิดีโอตัวแรก
    video_url = get_first_youtube_url(query)
    
    # เปิดผ่าน Chrome ทันที
    open_with_chrome(video_url)

class TelegramControlBot:
    def __init__(self, token: str, allowed_chat_id: str = ""):
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.app = None

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        
        reply = (
            f"📊 **รายงานสถานะคอมพิวเตอร์ค่ะ**\n"
            f"• CPU Usage: {cpu}%\n"
            f"• RAM Usage: {ram}%\n"
            f"• Disk Usage: {disk}%"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    async def shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        os.system("shutdown /s /t 60")
        await update.message.reply_text("⚠️ **รายงานค่ะ:** กำลังจะปิดคอมพิวเตอร์ภายใน 60 วินาทีค่ะ! (พิมพ์ /cancel_shutdown เพื่อยกเลิก)")

    async def cancel_shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        os.system("shutdown /a >nul 2>&1")
        await update.message.reply_text("✅ **รายงานค่ะ:** ยกเลิกคำสั่งปิดคอมพิวเตอร์เรียบร้อยแล้วค่ะ")

    def run(self):
        """รัน Telegram Bot ใน Background Thread"""
        if not self.token:
            print("⚠️ ไม่พบ Telegram Bot Token ใน config.json")
            return

        self.app = ApplicationBuilder().token(self.token).build()
        
        self.app.add_handler(CommandHandler("start", help_command))
        self.app.add_handler(CommandHandler("help", help_command))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("shutdown", self.shutdown))
        self.app.add_handler(CommandHandler("cancel_shutdown", self.cancel_shutdown))
        self.app.add_handler(CommandHandler("open", open_program))
        self.app.add_handler(CommandHandler("close", close_program))
        self.app.add_handler(CommandHandler("play", play_music))

        print("📱 [Telegram Bot] เริ่มต้นทำงานสแตนด์บายรับคำสั่งจากมือถือแล้วค่ะ")
        self.app.run_polling(drop_pending_updates=True)


def start_telegram_bot_thread(token: str):
    """ฟังก์ชันเรียกเปิดเธรด Telegram Bot จาก main.py"""
    if not token:
        return None
    bot = TelegramControlBot(token)
    t = threading.Thread(target=bot.run, daemon=True)
    t.start()
    return bot