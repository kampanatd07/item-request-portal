import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Account,
    CodeGroup,
    Factory,
    ItemRequest,
    ItemSnapshot,
    RequestEvent,
    RunningRegister,
)
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


def _retire(db: Session, code: str, req: ItemRequest, reason: str, account: Account) -> None:
    """Retire a thrown-away code in the caller's transaction; a refusal undoes it all.

    Only Central Codes (11 ASCII digits) are retired. Before STORY-010 override
    accepted any text up to 20 characters; such a value was never a register
    number, and retired_codes.code is 11 wide (PostgreSQL would refuse it and
    leave the request impossible to reject).
    """
    from app.services.codegen import CodegenError, retire_code

    if not re.fullmatch(r"[0-9]{11}", code or ""):
        return

    try:
        retire_code(db, code, request_id=req.id, reason=reason, actor=account.email)
    except CodegenError as e:
        db.rollback()
        raise RequestError(str(e)) from e


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
    return req.originator_name


def _check_originator(db: Session, name: str | None,
                      email: str | None) -> tuple[str | None, str | None]:
    """Normalised originator name and email, or a Thai RequestError.

    The email must belong to a named person, look like an Account email, and
    use an active allowed domain (Settings page) — notification emails carry
    internal item data, so a typo must not send them outside the company.
    """
    import unicodedata

    from app.services.auth import _EMAIL_RE
    from app.services.config_admin import active_mail_domains
    from app.services.snapshots import fix_thai

    # NFC then recompose SARA AM, never NFKC (HANDOFF §6.2), so a name typed as
    # NIKHAHIT + SARA AA is stored the same way as everywhere else.
    name = " ".join(fix_thai(unicodedata.normalize("NFC", name or "")).split()) or None
    email = (email or "").strip().lower() or None
    # Column limits: PostgreSQL raises instead of truncating (a 500, not Thai).
    if name is not None and len(name) > 100:
        raise RequestError("ชื่อผู้ขอจริงยาวเกิน 100 ตัวอักษร")
    if email is None:
        return name, None
    if len(email) > 254:
        raise RequestError("อีเมลผู้ขอจริงยาวเกิน 254 ตัวอักษร")
    if name is None:
        raise RequestError("ใส่อีเมลผู้ขอจริงแล้วต้องใส่ชื่อในช่อง \"ขอแทน\" ด้วย")
    if not _EMAIL_RE.fullmatch(email):
        raise RequestError("รูปแบบอีเมลผู้ขอจริงไม่ถูกต้อง")
    allowed = active_mail_domains(db)
    if not allowed:
        raise RequestError("ยังไม่มีโดเมนอีเมลที่อนุญาต — ผู้ดูแลระบบเพิ่มได้ในหน้าตั้งค่า "
                           "ยังใส่อีเมลผู้ขอจริงไม่ได้")
    if email.rsplit("@", 1)[1] not in allowed:
        raise RequestError(f"อีเมลผู้ขอจริงต้องเป็นโดเมนของบริษัท ({', '.join(sorted(allowed))})")
    return name, email


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
    originator_email: str | None = None,
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
        originator_email = None
    on_behalf_of, originator_email = _check_originator(db, on_behalf_of, originator_email)
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
        originator_name=on_behalf_of,
        originator_email=originator_email,
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
    if on_behalf_of:
        lines.append(ON_BEHALF_PREFIX + on_behalf_of
                     + (f" <{originator_email}>" if originator_email else ""))
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
        # The code also stays on the request (and its unique constraint); the
        # Retired Code is what later checks read (STORY-010).
        db.add(RequestEvent(
            request_id=req.id, actor=account.email, action="code_burned",
            detail=f"code {burned_code} ถูกทิ้งถาวร (ไม่อนุมัติหลังออกรหัส)",
        ))
        _retire(db, burned_code, req, "rejected", account)

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
        _retire(db, old_code, req, "reissued", account)
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


# More numbers than this thrown away by one override need explicit confirmation
# (STORY-010 grilling Q4): a one-digit typo must not burn thousands silently.
SKIP_CONFIRM_LIMIT = 10


@dataclass
class OverrideCheck:
    """What overriding a request's code with `code` would do (read-only).

    Numbers skipped when the register moves up are split: those the group
    master holds are real codes in use and are left alone; the rest would be
    thrown away (Retired Codes, reason `skipped`).
    """

    code: str
    current_code: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    item_name: str | None = None
    register_last: int | None = None
    to_retire: list[str] = field(default_factory=list)
    skipped_in_master: int = 0
    skipped_already_used: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def advances_register(self) -> bool:
        return self.register_last is not None and int(self.code[7:]) > self.register_last

    @property
    def needs_confirmation(self) -> bool:
        return len(self.to_retire) > SKIP_CONFIRM_LIMIT


def check_override(db: Session, req: ItemRequest, code: str) -> OverrideCheck:
    """Every STORY-010 rule for putting `code` on `req`, without changing anything.

    Override is for one case: the item already has Central Code X in the group
    master but not yet in this Plant's AX. The screen shows this before saving;
    override_code runs it again under the locks.
    """
    from app.services.codegen import (
        central_code,
        code_on_request,
        is_retired,
        master_codes,
        master_loaded,
        on_requests_among,
        retired_among,
    )

    code = (code or "").strip()
    check = OverrideCheck(code=code, current_code=req.generated_code)
    if req.status != "approved":
        check.errors.append("แก้รหัสได้เฉพาะคำขอที่อนุมัติแล้วและยังไม่ export")
        return check
    if code and code == req.generated_code:
        check.errors.append("รหัสนี้เป็นรหัสปัจจุบันของคำขออยู่แล้ว")
        return check
    group = req.group.code
    sub = req.subgroup.code if req.subgroup else None
    if not re.fullmatch(r"[0-9]{11}", code):
        check.errors.append("รหัสต้องเป็นตัวเลข 11 หลัก")
        return check
    if sub is None or code[:3] != group or code[3:5] != sub:
        check.errors.append(
            f"รหัส {code} ไม่ตรงกับหมวดของคำขอ ({group}-{sub or '??'}) — "
            "หลัก 1–5 ต้องเป็นหมวดและหมวดย่อยเดียวกัน")
        return check
    if code[5:7] != "00":
        check.errors.append("หลัก 6–7 ของรหัสต้องเป็น 00")
        return check
    if not master_loaded(db):
        check.errors.append("ยังไม่มี Master ที่จัดหมวดแล้ว — อัปโหลดในหน้า Snapshot ก่อน")
        return check
    found = master_codes(db, [code])
    if code not in found:
        check.errors.append(f"ไม่พบรหัส {code} ใน Master ของกลุ่ม — ใช้ได้เฉพาะรหัสที่กลุ่มออกแล้ว")
        return check
    check.item_name = found[code]

    source = snapshots.source_for_factory(db, req.factory_id)
    if snapshots.latest_import(db, source) is None:
        check.warnings.append(
            f"ยังไม่มี snapshot ของโรงงาน {req.factory.code} — ตรวจไม่ได้ว่ามีรหัสนี้ใน AX แล้วหรือไม่")
    elif db.scalar(select(ItemSnapshot.id).where(
            ItemSnapshot.source == source, ItemSnapshot.item_number == code)) is not None:
        if source == "D365":
            # One combined D365 snapshot for APM/APG/ACM with no company column:
            # X may belong to another plant, which is exactly the override case.
            # Warn until the snapshot is plant-aware (STORY-012; Peter, 2026-10-01).
            check.warnings.append(
                "รหัสนี้มีอยู่ใน D365 (APM/APG/ACM) แล้ว — ระบบแยกไม่ได้ว่าเป็นของโรงงานไหน "
                "ตรวจก่อน import")
        else:
            check.errors.append(
                f"รหัส {code} มีอยู่ในระบบของโรงงาน {req.factory.code} แล้ว — "
                f"ให้ไม่อนุมัติคำขอนี้พร้อมเหตุผล \"ซ้ำกับ {code}\" แทน")
            return check

    if is_retired(db, code):
        check.errors.append(f"รหัส {code} ถูกทิ้งไปแล้ว — ใช้ซ้ำไม่ได้")
        return check
    if code_on_request(db, code, other_than=req.id):
        check.errors.append(f"รหัส {code} ถูกใช้กับคำขออื่นแล้ว")
        return check

    reg = db.scalar(select(RunningRegister).where(
        RunningRegister.group_code == group, RunningRegister.sub_code == sub))
    check.register_last = reg.last_running if reg else 0
    running = int(code[7:])
    if running > check.register_last:
        between = [central_code(group, sub, n)
                   for n in range(check.register_last + 1, running)]
        # One query per kind for the whole range: a big jump must stay fast
        # while the request and register rows are locked.
        in_master = master_codes(db, between)
        used = retired_among(db, between) | on_requests_among(db, between)
        for c in between:
            if c in in_master:
                check.skipped_in_master += 1
            elif c in used:
                check.skipped_already_used += 1
            else:
                check.to_retire.append(c)
        if check.needs_confirmation:
            check.warnings.append(
                f"Register หมวด {group}-{sub} จะขยับจาก {check.register_last} เป็น {running} "
                f"และเลข {len(check.to_retire)} ตัวจะถูกทิ้งถาวร — ต้องยืนยันก่อน")
    return check


def override_code(
    db: Session, request_id: int, *, new_code: str, account: Account,
    reason: str = "", confirm_skip: bool = False, expected: dict | None = None,
) -> ItemRequest:
    """Put the group master's Central Code X on an approved request (STORY-010).

    All rules are in check_override, re-run here under the locks (request row,
    then register row — the same order as Approval and re-issue). If X is above
    the register, the register moves up to it and every skipped number the
    group master does not hold is retired. The replaced code is retired too.
    """
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
    if new_code == old:
        return req
    reason = " ".join((reason or "").split())
    if not reason:
        raise RequestError("กรุณาระบุเหตุผลที่แก้รหัส")

    from app.services.codegen import lock_register, retire_many

    reg = lock_register(db, req.group.code, req.subgroup.code) if req.subgroup else None
    check = check_override(db, req, new_code)
    if not check.ok:
        db.rollback()
        raise RequestError(check.errors[0])
    if expected is not None:
        # The screen showed a preview; save only if nothing changed since.
        from app.services.override_preview import CHECK_AGAIN, plan_of

        changed = [key for key, value in plan_of(check).items() if expected.get(key) != value]
        if changed:
            db.rollback()
            labels = {"code": "รหัส", "item_name": "ชื่อ item ใน Master",
                      "current_code": "รหัสปัจจุบันของคำขอ",
                      "register_last": "เลขล่าสุดของ register", "to_retire": "จำนวนเลขที่จะทิ้ง",
                      "to_retire_digest": "เลขที่จะทิ้ง", "in_master": "จำนวนที่มีใน master",
                      "already_used": "จำนวนที่ใช้อยู่แล้ว"}
            raise RequestError(
                "ข้อมูลเปลี่ยนไปหลังตรวจรหัส ("
                + ", ".join(dict.fromkeys(labels[k] for k in changed))
                + f") — {CHECK_AGAIN}")
    if check.needs_confirmation and not confirm_skip:
        db.rollback()
        raise RequestError(
            f"รหัสนี้จะทำให้เลข {len(check.to_retire)} ตัวถูกทิ้งถาวร — ต้องติ๊กยืนยันก่อนบันทึก")

    if check.advances_register:
        running = int(new_code[7:])
        db.add(RequestEvent(
            request_id=req.id, actor=account.email, action="register_advanced",
            detail=(f"{req.group.code}-{req.subgroup.code}: {reg.last_running} -> {running} "
                    f"(ทิ้ง {len(check.to_retire)}, มีใน Master {check.skipped_in_master}, "
                    f"ใช้อยู่แล้ว {check.skipped_already_used})"),
        ))
        reg.last_running = running
        retire_many(db, check.to_retire, request_id=req.id, reason="skipped",
                    actor=account.email)
    req.generated_code = new_code
    db.add(RequestEvent(
        request_id=req.id, actor=account.email, action="code_overridden",
        detail=f"{old} -> {new_code} · เหตุผล: {reason}",
    ))
    _retire(db, old, req, "overridden", account)
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
