"""The signed hand-off from "check code" to "confirm override" (STORY-010 ticket 04).

The token proves the Administrator saw this exact preview: which request,
which code, and what it would do to the register. It carries no authority to
change anything — override_code recomputes everything under its locks and
only compares with what the token says was shown; a mismatch is refused and
the Administrator checks again. Signed with SECRET_KEY under its own salt, so a
session cookie (or any other signed value) never passes as a preview token.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeSerializer

from app.config import settings
from app.models import Account, ItemRequest
from app.services.requests import OverrideCheck, RequestError

SALT = "override-preview"
MAX_AGE = timedelta(minutes=10)
CHECK_AGAIN = "กรุณากดตรวจสอบรหัสใหม่"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=SALT)


def _epoch(now: datetime) -> int:
    return int(now.replace(tzinfo=timezone.utc).timestamp())


def plan_of(check: OverrideCheck) -> dict:
    """What the Administrator is shown and agrees to; compared again at confirm."""
    return {
        "code": check.code,
        # The name the Administrator confirmed against: a re-uploaded master
        # that now names another item must not slip through.
        "item_name": check.item_name,
        "current_code": check.current_code,
        "register_last": check.register_last,
        "to_retire": len(check.to_retire),
        "to_retire_digest": hashlib.sha256(",".join(check.to_retire).encode()).hexdigest()[:16],
        "in_master": check.skipped_in_master,
        "already_used": check.skipped_already_used,
    }


def issue(check: OverrideCheck, req: ItemRequest, account: Account, now: datetime) -> str:
    return _serializer().dumps({
        "rid": req.id, "aid": account.id, "at": _epoch(now), "plan": plan_of(check),
    })


def read(token: str, req: ItemRequest, account: Account, now: datetime) -> dict:
    """The plan a valid token was issued for, or a Thai RequestError."""
    try:
        data = _serializer().loads(token or "")
        rid, aid, at, plan = int(data["rid"]), int(data["aid"]), int(data["at"]), data["plan"]
    except (BadSignature, KeyError, TypeError, ValueError):
        raise RequestError(f"ไม่พบผลการตรวจรหัสที่ถูกต้อง — {CHECK_AGAIN}") from None
    if rid != req.id:
        raise RequestError(f"ผลการตรวจนี้เป็นของคำขออื่น — {CHECK_AGAIN}")
    if aid != account.id:
        raise RequestError(f"ผลการตรวจนี้เป็นของผู้ใช้อื่น — {CHECK_AGAIN}")
    if _epoch(now) - at > MAX_AGE.total_seconds():
        raise RequestError(f"ผลการตรวจหมดอายุ (เกิน 10 นาที) — {CHECK_AGAIN}")
    return plan
