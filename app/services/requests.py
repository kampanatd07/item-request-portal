from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CodeGroup, ItemRequest, RequestEvent
from app.services import snapshots

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


def _canonical_uom(db: Session, raw: str | None) -> str | None:
    from app.services.config_admin import canonical_uom

    return canonical_uom(db, raw)


def _resolve_search_name(db: Session, given: str | None, item_name: str) -> str:
    if given and given.strip():
        return given.strip()[:60]
    from app.services.classifier import classify
    from app.services.llm_backend import get_llm

    return classify(db, item_name, llm=get_llm())["suggestion"][:60]


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
    variant: str | None = None,
    spec_note: str | None = None,
    uom: str | None = None,
    search_name: str | None = None,
    purchase_price: str | None = None,
    procurement_category: str | None = None,
) -> ItemRequest:
    if not requester_name.strip():
        raise RequestError("กรุณากรอกชื่อผู้ขอ")
    if not item_name.strip():
        raise RequestError("กรุณากรอกชื่อเรียกสินค้า")

    # Compose the standard product name (แบบ B) — the requester's fields are
    # structure, the name is an output, not an input.
    from app.services.naming import NamingError, compose_name

    try:
        composed_name = compose_name(
            item_name, brand=brand, model=model, size=size, detail=variant
        )
    except NamingError as e:
        raise RequestError(str(e)) from e

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
        item_name=composed_name,
        brand=brand or None,
        model=model or None,
        size=size or None,
        variant=variant or None,
        spec_note=spec_note or None,
        uom=_canonical_uom(db, uom),
        # If the requester left search name blank, classify the item name into a
        # canonical term so items still cluster (dictionary + optional LLM).
        search_name=_resolve_search_name(db, search_name, composed_name),
        purchase_price=purchase_price or None,
        procurement_category=procurement_category or None,
        status="submitted",
    )
    db.add(req)
    db.flush()

    # Record top duplicate candidates at submission time in the audit trail, so
    # the reviewer sees what the requester saw even after the snapshot changes.
    source = snapshots.source_for_factory(db, factory_id)
    query = " ".join(p for p in [item_name, brand or "", model or ""] if p)
    matches = snapshots.search_similar(db, source=source, query=query, limit=3)
    detail = (
        "duplicate candidates: "
        + "; ".join(f"{i.item_number} {i.name[:60]} ({s:.0%})" for i, s in matches)
        if matches
        else None
    )
    db.add(
        RequestEvent(
            request_id=req.id, actor=requester_email, action="submitted", detail=detail
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

    # Approval mints the item code in the same transaction; the unique
    # constraint on generated_code is the last line of defense against races.
    if new_status == "approved" and req.generated_code is None:
        from app.services.codegen import CodegenError, generate_code

        try:
            code = generate_code(db, req)
        except CodegenError as e:
            db.rollback()
            raise RequestError(str(e)) from e
        req.generated_code = code
        db.add(
            RequestEvent(
                request_id=req.id, actor=actor, action="code_generated", detail=code
            )
        )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise RequestError(
            "ออกรหัสชนกับคำขออื่นที่เพิ่งอนุมัติ — กด approve อีกครั้ง"
        ) from e
    return req


def edit_name(db: Session, request_id: int, *, new_name: str, actor: str) -> ItemRequest:
    """Procurement-only override of the composed product name, before export."""
    req = db.get(ItemRequest, request_id)
    if req is None:
        raise RequestError("ไม่พบคำขอนี้")
    if req.status in {"exported", "created", "notified"}:
        raise RequestError("แก้ชื่อไม่ได้หลัง export แล้ว")
    new_name = " ".join(new_name.split())
    if not new_name:
        raise RequestError("กรุณากรอกชื่อ")
    old = req.item_name
    if new_name == old:
        return req
    req.item_name = new_name
    db.add(
        RequestEvent(
            request_id=req.id, actor=actor, action="name_edited",
            detail=f"{old} -> {new_name}",
        )
    )
    db.commit()
    return req


def override_code(
    db: Session, request_id: int, *, new_code: str, actor: str
) -> ItemRequest:
    req = db.get(ItemRequest, request_id)
    if req is None:
        raise RequestError("ไม่พบคำขอนี้")
    if req.status not in {"approved"}:
        raise RequestError("แก้รหัสได้เฉพาะคำขอที่อนุมัติแล้วและยังไม่ export")
    new_code = new_code.strip()
    if not new_code:
        raise RequestError("กรุณากรอกรหัส")
    old = req.generated_code
    req.generated_code = new_code
    db.add(
        RequestEvent(
            request_id=req.id, actor=actor, action="code_overridden",
            detail=f"{old} -> {new_code}",
        )
    )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise RequestError("รหัสนี้ถูกใช้กับคำขออื่นแล้ว") from e
    return req


def list_queue(db: Session, status: str | None = None) -> list[ItemRequest]:
    stmt = select(ItemRequest).order_by(ItemRequest.created_at.desc())
    if status:
        stmt = stmt.where(ItemRequest.status == status)
    return list(db.scalars(stmt))
