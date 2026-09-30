from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, CodeGroup, Factory, ItemRequest, RequestEvent
from app.services import snapshots
from app.services.auth import has_role

# Allowed status transitions: guards against double-clicks and stale queue pages.
TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"in_review", "approved", "rejected", "needs_info"},
    "in_review": {"approved", "rejected", "needs_info"},
    "needs_info": {"submitted", "rejected"},
    # approved -> rejected: Administrator only, reason required, code burned.
    "approved": {"exported", "rejected"},
    "exported": {"created"},
    "created": {"notified"},
}


# Marks the originator line in a "submitted" event's detail, when Procurement
# submits for someone else. Stored in the audit trail, not in spec_note.
ON_BEHALF_PREFIX = "ขอแทน: "


class RequestError(Exception):
    """Domain error with a user-facing Thai message."""


class RequestForbidden(RequestError):
    """The acting Account's Role may not do this; routes answer 403."""


def _get_locked(db: Session, request_id: int) -> ItemRequest | None:
    """Load a request with its row locked until commit (Postgres; SQLite ignores it).

    Every change to a request goes through here, and export locks the same rows,
    so two actions on one request run one after the other. Each caller checks
    status only after this returns, i.e. after it holds the lock and sees the
    latest committed row — e.g. a re-categorise and an export racing on an
    approved request can no longer leave an exported request with a new code.
    """
    return db.scalar(
        select(ItemRequest)
        .where(ItemRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _require_administrator(account: Account) -> None:
    """Guard for the actions that consume the Running Register.

    Governance v1 §3: only the Data Steward (Administrator) issues running
    numbers, and an issued number is used forever. Callers check this before
    touching the register, so a refused attempt never burns a number.
    """
    if not has_role(account, "administrator"):
        raise RequestForbidden("เฉพาะผู้ดูแลระบบ (Data Steward) เท่านั้นที่ทำรายการนี้ได้")


def originator_of(req: ItemRequest) -> str | None:
    """Who really asked for this request, if it was submitted on their behalf."""
    for event in req.events:
        if event.action == "submitted" and event.detail:
            for line in event.detail.splitlines():
                if line.startswith(ON_BEHALF_PREFIX):
                    return line.removeprefix(ON_BEHALF_PREFIX)
    return None


def _canonical_uom(db: Session, raw: str | None) -> str | None:
    from app.services.config_admin import canonical_uom

    return canonical_uom(db, raw)


def _resolve_search_name(
    db: Session, given: str | None, base_name: str, factory_id: int,
    product_type: str | None = None,
) -> str:
    if given and given.strip():
        return given.strip()[:60]
    from app.services.classifier import classify
    from app.services.llm_backend import get_llm

    source = snapshots.source_for_factory(db, factory_id)
    has_snapshot = snapshots.latest_import(db, source) is not None
    return classify(
        db, base_name, llm=get_llm(),
        snapshot_source=source if has_snapshot else None,
        product_type=product_type,
    )["suggestion"][:60]


def submit_request(
    db: Session,
    account: Account,
    *,
    factory_id: int | None,
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
    on_behalf_of: str | None = None,
) -> ItemRequest:
    """Submit a request in the Account's own name.

    A Requester always submits for their own Plant, whatever `factory_id` says
    (AC3); Procurement and Administrator choose it. `on_behalf_of` names who
    really asked (e.g. someone who phoned Procurement); it is dropped for a
    Requester and kept in the audit trail, not in the item's spec.
    """
    if account.role == "requester":
        factory_id = account.factory_id
        on_behalf_of = None
    factory = db.get(Factory, factory_id) if factory_id is not None else None
    if factory is None or not factory.active:
        raise RequestError("กรุณาเลือกโรงงาน")
    if not item_name.strip():
        raise RequestError("กรุณากรอกชื่อเรียกสินค้า")

    group = db.get(CodeGroup, group_id)
    if group is None or group.code_system_id != code_system_id or not group.active:
        raise RequestError("หมวดสินค้าไม่ถูกต้องสำหรับระบบที่เลือก")

    # A system whose groups have children requires a subgroup (e.g. CBD stock subcategory).
    children = db.scalars(
        select(CodeGroup).where(CodeGroup.parent_id == group_id, CodeGroup.active)
    ).first()
    if children is not None and subgroup_id is None:
        raise RequestError("หมวดนี้ต้องเลือกหมวดย่อยด้วย")
    sub = None
    if subgroup_id is not None:
        sub = db.get(CodeGroup, subgroup_id)
        if sub is None or sub.parent_id != group_id or not sub.active:
            raise RequestError("หมวดย่อยไม่ถูกต้อง")

    # Compose the standard product name. The [CATEGORY] segment is the
    # sub-category's taxonomy Name Prefix, so the name and the code always
    # describe the same category. Runs after validation so the prefix is trusted.
    from app.services.naming import NamingError, compose_name
    from app.services.units import normalize_size

    prefix_source = sub or group
    try:
        composed_name = compose_name(
            item_name, brand=brand, model=model,
            size=normalize_size(size), detail=variant,
            category_prefix=prefix_source.name_prefix if prefix_source else None,
        )
    except NamingError as e:
        raise RequestError(str(e)) from e

    req = ItemRequest(
        requester_name=account.display_name,
        requester_email=account.email,
        factory_id=factory_id,
        code_system_id=code_system_id,
        group_id=group_id,
        subgroup_id=subgroup_id,
        item_name=composed_name,
        brand=brand or None,
        model=model or None,
        size=normalize_size(size) or None,
        variant=variant or None,
        spec_note=spec_note or None,
        uom=_canonical_uom(db, uom),
        # If the requester left search name blank, classify the BASE name into a
        # canonical category term (dictionary -> master neighbours -> LLM).
        search_name=_resolve_search_name(
            db, search_name, item_name, factory_id,
            product_type=(sub or group).product_type,
        ),
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
    lines = []
    if on_behalf_of and on_behalf_of.strip():
        lines.append(ON_BEHALF_PREFIX + " ".join(on_behalf_of.split()))
    if matches:
        lines.append(
            "duplicate candidates: "
            + "; ".join(f"{i.item_number} {i.name[:60]} ({s:.0%})" for i, s in matches)
        )
    db.add(
        RequestEvent(
            request_id=req.id, actor=account.email, action="submitted",
            detail="\n".join(lines) or None,
        )
    )
    db.commit()
    return req


def change_status(
    db: Session, request_id: int, *, new_status: str, account: Account,
    note: str | None = None,
) -> ItemRequest:
    # Approval mints a code from the register: Administrator only.
    if new_status == "approved":
        _require_administrator(account)
    req = _get_locked(db, request_id)
    if req is None:
        raise RequestError("ไม่พบคำขอนี้")
    allowed = TRANSITIONS.get(req.status, set())
    if new_status not in allowed:
        raise RequestError(
            f"เปลี่ยนสถานะจาก {req.status} เป็น {new_status} ไม่ได้"
        )
    # Rejecting an approved request throws away an issued number for good, so
    # only the Data Steward may do it (checked after the lock, on fresh status),
    # and must say why.
    burned_code = None
    if req.status == "approved" and new_status == "rejected":
        _require_administrator(account)
        if not (note or "").strip():
            raise RequestError("กรุณาระบุเหตุผลที่ไม่อนุมัติคำขอที่ออกรหัสแล้ว")
        burned_code = req.generated_code
    req.status = new_status
    if note:
        req.review_note = note
    db.add(RequestEvent(request_id=req.id, actor=account.email, action=new_status,
                        detail=note))
    if burned_code:
        # The code stays on the request (and its unique constraint), so the
        # number can never be issued or overridden onto another item.
        db.add(RequestEvent(
            request_id=req.id, actor=account.email, action="code_burned",
            detail=f"code {burned_code} ถูกทิ้งถาวร (ไม่อนุมัติหลังออกรหัส)",
        ))

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
                request_id=req.id, actor=account.email, action="code_generated",
                detail=code,
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


def edit_name(
    db: Session, request_id: int, *, new_name: str, account: Account
) -> ItemRequest:
    """Procurement-only override of the composed product name, before export."""
    req = _get_locked(db, request_id)
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
            request_id=req.id, actor=account.email, action="name_edited",
            detail=f"{old} -> {new_name}",
        )
    )
    db.commit()
    return req


def change_category(
    db: Session, request_id: int, *, subgroup_id: int, account: Account
) -> ItemRequest:
    """Re-categorise a request; the correction is fed back so similar future
    requests start out right.

    Before a code: Procurement may do it, to any Group. After a code
    (Administrator only, only while still `approved`, i.e. not yet in AX, and
    only within the same Item Group): the code encodes the category, so a new
    code is issued from the new sub-category's register and the old number is
    burned for good.
    """
    req = _get_locked(db, request_id)
    if req is None:
        raise RequestError("ไม่พบคำขอนี้")
    if req.generated_code:
        _require_administrator(account)
        if req.status != "approved":
            raise RequestError("เปลี่ยนหมวดไม่ได้หลัง export แล้ว — รหัสอยู่ใน AX แล้ว")

    sub = db.get(CodeGroup, subgroup_id)
    if sub is None or sub.parent_id is None or not sub.active:
        raise RequestError("หมวดย่อยไม่ถูกต้อง")
    parent = db.get(CodeGroup, sub.parent_id)
    if parent.code_system_id != req.code_system_id:
        raise RequestError("หมวดย่อยไม่ถูกต้องสำหรับระบบรหัสของคำขอนี้")
    # Governance §4: the Data Steward may move a coded item between
    # Sub-Categories, but moving it to another Item Group needs the Data Owner,
    # an approval step outside v1. Before a code, any move is fine.
    if req.generated_code and parent.id != req.group_id:
        raise RequestError(
            "ย้ายข้าม Item Group หลังออกรหัสแล้วต้องให้ Data Owner อนุมัติ "
            "(Governance §4) — ให้กด 'ไม่อนุมัติ' คำขอนี้ แล้วส่งคำขอใหม่ในหมวดที่ถูกต้อง"
        )
    old = f"{req.group.code}-{req.subgroup.code}" if req.subgroup else req.group.code
    new = f"{parent.code}-{sub.code}"
    if old == new:
        return req

    req.group_id = parent.id
    req.subgroup_id = sub.id
    db.add(
        RequestEvent(
            request_id=req.id, actor=account.email, action="category_changed",
            detail=f"{old} -> {new}",
        )
    )
    if req.generated_code:
        from app.services.codegen import CodegenError, generate_code

        db.flush()
        db.refresh(req)  # load the new group/subgroup for the code prefix
        old_code = req.generated_code
        try:
            new_code = generate_code(db, req)
        except CodegenError as e:
            db.rollback()
            raise RequestError(str(e)) from e
        req.generated_code = new_code
        db.add(
            RequestEvent(
                request_id=req.id, actor=account.email, action="code_reissued",
                detail=f"{old_code} -> {new_code}",
            )
        )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise RequestError("ออกรหัสใหม่ชนกับคำขออื่น — ลองอีกครั้ง") from e

    from app.services.categorizer import learn_from_correction

    learn_from_correction(
        db, name=req.item_name, group_code=parent.code, sub_code=sub.code,
        actor=account.email,
    )
    return req


def override_code(
    db: Session, request_id: int, *, new_code: str, account: Account
) -> ItemRequest:
    # Not yet validated against the register — see STORY-010.
    _require_administrator(account)
    req = _get_locked(db, request_id)
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
            request_id=req.id, actor=account.email, action="code_overridden",
            detail=f"{old} -> {new_code}",
        )
    )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise RequestError("รหัสนี้ถูกใช้กับคำขออื่นแล้ว") from e
    return req


def list_my_requests(db: Session, account: Account) -> list[ItemRequest]:
    """The Account's own requests, newest first ("My requests").

    Matched on email, which never changes for an Account. Compared without case
    or surrounding spaces, since requests typed in before login existed may
    carry the address as the person wrote it.
    """
    return list(db.scalars(
        select(ItemRequest)
        .where(func.lower(func.trim(ItemRequest.requester_email)) == account.email.lower())
        .order_by(ItemRequest.created_at.desc(), ItemRequest.id.desc())
    ))


def list_queue(db: Session, status: str | None = None) -> list[ItemRequest]:
    stmt = select(ItemRequest).order_by(ItemRequest.created_at.desc())
    if status:
        stmt = stmt.where(ItemRequest.status == status)
    return list(db.scalars(stmt))
