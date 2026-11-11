from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import settings
from app.services.auth import has_role
from app.services.thai_labels import HINT_TH_MAX, NAME_TH_MAX

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


def category_label(group) -> str:
    """'900 — Spare Parts & Mechanical Parts (อะไหล่…)': the Thai name, when
    set, follows the English one (STORY-019). Display only."""
    label = f"{group.code} — {group.name}"
    return f"{label} ({group.name_th})" if group.name_th else label


templates.env.globals["category_label"] = category_label
templates.env.globals["NAME_TH_MAX"] = NAME_TH_MAX
templates.env.globals["HINT_TH_MAX"] = HINT_TH_MAX

# What each status means and who acts next, in plain Thai (STORY-018). The
# one source for the status legend, badge tooltips and the help page; Peter
# reviews the wording in the browser (2026-11-09).
STATUS_HELP: dict[str, tuple[str, str]] = {
    "submitted": ("ส่งถึงจัดซื้อแล้ว รอจัดซื้อตรวจ", "จัดซื้อ"),
    "in_review": ("จัดซื้อตรวจแล้ว รอผู้ดูแลระบบอนุมัติและออกรหัส", "ผู้ดูแลระบบ"),
    "needs_info": ("จัดซื้อต้องการข้อมูลเพิ่ม อ่านหมายเหตุจากจัดซื้อ แล้วกด “แก้ไขและส่งกลับ”", "ผู้ขอ"),
    "approved": ("อนุมัติและได้รหัสแล้ว แต่ยังไม่อยู่ใน AX/D365 จึงยังสั่งซื้อไม่ได้", "จัดซื้อ (export ไฟล์)"),
    "rejected": ("ไม่อนุมัติ อ่านเหตุผลในหมายเหตุจากจัดซื้อ", "-"),
    "exported": ("ออกไฟล์ import แล้ว รอจัดซื้อนำเข้า AX/D365", "จัดซื้อ"),
    "created": ("สร้างใน AX/D365 แล้ว สั่งซื้อได้", "-"),
    "notified": ("สร้างใน AX/D365 แล้ว และส่งอีเมลแจ้งผู้ขอแล้ว สั่งซื้อได้", "-"),
}
templates.env.globals["status_help"] = STATUS_HELP
# The requester's progress bar: steps, and how many each status has finished.
# A rejected request has no position on it.
PROGRESS_STEPS = ("ส่งคำขอ", "จัดซื้อตรวจ", "อนุมัติ ได้รหัส", "สร้างใน AX")
STATUS_STEPS_DONE = {"submitted": 1, "needs_info": 1, "in_review": 2, "approved": 3,
                     "exported": 3, "created": 4, "notified": 4}
templates.env.globals["progress_steps"] = PROGRESS_STEPS
templates.env.globals["status_steps_done"] = STATUS_STEPS_DONE
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

