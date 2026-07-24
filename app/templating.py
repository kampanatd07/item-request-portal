from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_LABELS = {
    "submitted": "ส่งคำขอแล้ว",
    "in_review": "กำลังตรวจสอบ",
    "needs_info": "ขอข้อมูลเพิ่ม",
    "approved": "อนุมัติแล้ว",
    "rejected": "ไม่อนุมัติ",
    "exported": "ออกไฟล์ import แล้ว",
    "created": "สร้างในระบบแล้ว",
    "notified": "แจ้งผู้ขอแล้ว",
}
templates.env.globals["status_labels"] = STATUS_LABELS
