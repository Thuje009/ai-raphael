"""ระบบตรวจสอบสถานะสุขภาพคอมพิวเตอร์ (CPU, RAM, Disk) ของราฟาเอล"""
import psutil
from speech import speak

def check_pc_status(query=""):
    """ตรวจสอบสถานะ CPU, RAM และพื้นที่ดิสก์ แล้วรายงานผ่านเสียง"""
    try:
        # ตรวจสอบการใช้งาน CPU (เทียบเปอร์เซ็นต์แบบเฉลี่ย)
        cpu_usage = psutil.cpu_percent(interval=1)
        
        # ตรวจสอบหน่วยความจำ RAM
        ram = psutil.virtual_memory()
        ram_total_gb = ram.total / (1024 ** 3)
        ram_used_gb = ram.used / (1024 ** 3)
        ram_percent = ram.percent
        
        # ตรวจสอบพื้นที่ฮาร์ดดิสก์ (Drive C)
        disk = psutil.disk_usage('C:')
        disk_total_gb = disk.total / (1024 ** 3)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_percent = disk.percent
        
        # จัดรูปแบบข้อความรายงานให้กระชับและฟังง่าย
        report = (
            f"รายงานสถานะระบบค่ะ "
            f"ซีพียูใช้งานไป {cpu_usage:.1f} เปอร์เซ็นต์, "
            f"แรมใช้งานไป {ram_percent} เปอร์เซ็นต์ หรือประมาณ {ram_used_gb:.1f} จากทั้งหมด {ram_total_gb:.1f} กิกะไบต์, "
            f"และพื้นที่ไดรฟ์ซีว่างเหลืออยู่ประมาณ {disk_free_gb:.1f} กิกะไบต์ค่ะ"
        )
        
        speak(report)
    except Exception as e:
        speak(f"ไม่สามารถตรวจสอบสถานะคอมพิวเตอร์ได้ในขณะนี้ค่ะ {e}")