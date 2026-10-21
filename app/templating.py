from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import settings
from app.services.auth import has_role

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_LABELS = {
    "submitted": "ส่งคำขอแล้ว",
    "in_review": "ตรวจแล้ว รออนุมัติ",
    "needs_info": "ขอข้อมูลเพิ่ม",
    "approved": "อนุมัติแล้ว",
    "rejected": "ไม่อนุมัติ",
    "exported": "ออกไฟล์ import แล้ว",
    "created": "สร้างในระบบแล้ว",
    "notified": "แจ้งผู้ขอแล้ว",
}
templates.env.globals["status_labels"] = STATUS_LABELS
# Request-history rows that are not status changes (STORY-002).
templates.env.globals["event_labels"] = {
    "notify_not_applicable": "ไม่ต้องแจ้งทางอีเมล",
    "request_edited": "แก้ไขข้อมูลคำขอ",
    "name_prefix_changed": "เปลี่ยน prefix ตามหมวด",
}
# Which email is owed, on the resend list (STORY-002 ticket 06).
templates.env.globals["mail_kinds"] = {
    "created": "สร้างใน AX แล้ว",
    "needs_info": "ขอข้อมูลเพิ่ม",
    "rejected": "ไม่อนุมัติ",
}
templates.env.globals["has_role"] = has_role
templates.env.globals["session_hours"] = settings.session_max_hours

# The DB stores naive UTC; people read Thai time. Thailand has no daylight
# saving, so a fixed +07:00 offset is exact (and needs no tzdata on Windows).
THAI_TZ = timezone(timedelta(hours=7))


def thai_time(value: datetime, fmt: str = "%H:%M") -> str:
    """Format a naive-UTC datetime from the DB in Thai time (UTC+7)."""
    return value.replace(tzinfo=timezone.utc).astimezone(THAI_TZ).strftime(fmt)


templates.env.filters["thai_time"] = thai_time

