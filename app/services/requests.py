from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeGroup, ItemRequest, RequestEvent

# Allowed status transitions: guards against double-clicks and stale queue pages.
TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"in_review", "approved", "rejected", "needs_info"},
    "in_review": {"approved", "rejected", "needs_info"},
    "needs_info": {"submitted", "rejected"},
    "approved": {"exported"},
    "exported": {"created"},
    "created": {"notified"},
}


class RequestError(Exception):
    """Domain error with a user-facing Thai message."""


def submit_request(
    db: Session,
    *,
    requester_name: str,
    requester_email: str,
    factory_id: int,
    code_system_id: int,
    group_id: int,
    subgroup_id: int | None,
    item_name: str,
    brand: str | None = None,
    model: str | None = None,
    size: str | None = None,
    spec_note: str | None = None,
    uom: str | None = None,
) -> ItemRequest:
    if not requester_name.strip():
        raise RequestError("กรุณากรอกชื่อผู้ขอ")
    if not item_name.strip():
        raise RequestError("กรุณากรอกชื่อสินค้า")

    group = db.get(CodeGroup, group_id)
    if group is None or group.code_system_id != code_system_id or not group.active:
        raise RequestError("หมวดสินค้าไม่ถูกต้องสำหรับระบบที่เลือก")

    # A system whose groups have children requires a subgroup (e.g. CBD stock subcategory).
    children = db.scalars(
        select(CodeGroup).where(CodeGroup.parent_id == group_id, CodeGroup.active)
    ).first()
    if children is not None and subgroup_id is None:
        raise RequestError("หมวดนี้ต้องเลือกหมวดย่อยด้วย")
    if subgroup_id is not None:
        sub = db.get(CodeGroup, subgroup_id)
        if sub is None or sub.parent_id != group_id or not sub.active:
            raise RequestError("หมวดย่อยไม่ถูกต้อง")

    req = ItemRequest(
        requester_name=requester_name.strip(),
        requester_email=requester_email.strip(),
        factory_id=factory_id,
        code_system_id=code_system_id,
        group_id=group_id,
        subgroup_id=subgroup_id,
        item_name=item_name.strip(),
        brand=brand or None,
        model=model or None,
        size=size or None,
        spec_note=spec_note or None,
        uom=uom or None,
        status="submitted",
    )
    db.add(req)
    db.flush()
    db.add(
        RequestEvent(
            request_id=req.id, actor=requester_email, action="submitted", detail=None
        )
    )
    db.commit()
    return req


def change_status(
    db: Session, request_id: int, *, new_status: str, actor: str, note: str | None = None
) -> ItemRequest:
    req = db.get(ItemRequest, request_id)
    if req is None:
        raise RequestError("ไม่พบคำขอนี้")
    allowed = TRANSITIONS.get(req.status, set())
    if new_status not in allowed:
        raise RequestError(
            f"เปลี่ยนสถานะจาก {req.status} เป็น {new_status} ไม่ได้"
        )
    req.status = new_status
    if note:
        req.review_note = note
    db.add(RequestEvent(request_id=req.id, actor=actor, action=new_status, detail=note))
    db.commit()
    return req


def list_queue(db: Session, status: str | None = None) -> list[ItemRequest]:
    stmt = select(ItemRequest).order_by(ItemRequest.created_at.desc())
    if status:
        stmt = stmt.where(ItemRequest.status == status)
    return list(db.scalars(stmt))
