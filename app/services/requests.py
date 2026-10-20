import re
from dataclasses import asdict, dataclass, field

from sqlalchemy import func, or_, select
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
from app.services.auth import has_role, normalize_email

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


class RequestNotFound(RequestError):
    """No such request; routes answer 404."""


class RequestConflict(RequestError):
    """The request moved on since the page was opened; routes answer 409."""


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


def _check_originator(db: Session, name: str | None, email: str | None,
                      keep_email: str | None = None) -> tuple[str | None, str | None]:
    """Normalised originator name and email, or a Thai RequestError.

    The email must belong to a named person, look like an Account email, and
    use an active allowed domain (Settings page) — notification emails carry
    internal item data, so a typo must not send them outside the company.
    `keep_email`, the one already stored on a resubmitted request, skips the
    domain check: a domain switched off since must not block other edits
    (send-time checks still apply, see notify.recipients).
    """
    import unicodedata

    from app.services.auth import _EMAIL_RE
    from app.services.config_admin import active_mail_domains
    from app.services.snapshots import fix_thai

    # NFC then recompose SARA AM, never NFKC (HANDOFF §6.2), so a name typed as
    # NIKHAHIT + SARA AA is stored the same way as everywhere else.
    name = " ".join(fix_thai(unicodedata.normalize("NFC", name or "")).split()) or None
    email = normalize_email(email or "") or None
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
    if email == keep_email:
        return name, email
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
    fields = _validated_fields(
        db, factory_id, code_system_id=code_system_id, group_id=group_id,
        subgroup_id=subgroup_id, item_name=item_name, brand=brand, model=model, size=size,
        variant=variant, spec_note=spec_note, uom=uom, search_name=search_name,
        purchase_price=purchase_price, procurement_category=procurement_category,
    )

    req = ItemRequest(
        requester_name=account.display_name,
        requester_email=account.email,
        originator_name=on_behalf_of,
        originator_email=originator_email,
        factory_id=factory_id,
        **asdict(fields),
        status="submitted",
    )
    db.add(req)
    db.flush()

    # Record top duplicate candidates at submission time in the audit trail, so
    # the reviewer sees what the requester saw even after the snapshot changes.
    lines = []
    if on_behalf_of:
        lines.append(ON_BEHALF_PREFIX + on_behalf_of
                     + (f" <{originator_email}>" if originator_email else ""))
    duplicates = _duplicate_line(db, factory_id, item_name, brand, model)
    if duplicates:
        lines.append(duplicates)
    db.add(
        RequestEvent(
            request_id=req.id, actor=account.email, action="submitted",
            detail="\n".join(lines) or None,
        )
    )
    db.commit()
    return req


@dataclass
class RequestFields:
    """The validated, composed values of an Item Request's form fields, ready
    to set on the row; Plant and the originator are decided by the caller."""

    code_system_id: int
    group_id: int
    subgroup_id: int | None
    item_name: str
    base_name: str | None
    brand: str | None
    model: str | None
    size: str | None
    variant: str | None
    spec_note: str | None
    uom: str | None
    search_name: str
    purchase_price: str | None
    procurement_category: str | None


def name_prefix_of(group: CodeGroup | None, sub: CodeGroup | None) -> str | None:
    """The Name Prefix an Item Name in this category gets: the Sub-Category's
    when there is one (even if it has no prefix), the Group's only when there
    is no Sub-Category. One choice for composing and for checking a name."""
    source = sub or group
    return source.name_prefix if source else None


def _require_base_name(item_name: str | None) -> None:
    if not (item_name or "").strip():
        raise RequestError("กรุณากรอกชื่อเรียกสินค้า")


def _validated_fields(
    db: Session,
    factory_id: int,
    *,
    code_system_id: int,
    group_id: int,
    subgroup_id: int | None,
    item_name: str,
    brand: str | None,
    model: str | None,
    size: str | None,
    variant: str | None,
    spec_note: str | None,
    uom: str | None,
    search_name: str | None,
    purchase_price: str | None,
    procurement_category: str | None,
    classify_blank: bool = True,
) -> RequestFields:
    """Check the category and compose the Item Name from the form fields, or
    raise a Thai RequestError. Shared by a new submission and a resubmit
    (STORY-009), so the two can never drift. `item_name` is the Base Name."""
    _require_base_name(item_name)
    # The system must be one the Plant may request against, and switched on:
    # the same list the form offers (catalog.systems_for_factory). Before
    # STORY-009's closing review only the group was checked, so a hand-made
    # post could use another Plant's system or the inactive stock systems.
    from app.services.catalog import systems_for_factory

    if code_system_id not in {s.id for s in systems_for_factory(db, factory_id)}:
        raise RequestError("ระบบรหัสนี้ใช้กับโรงงานของคำขอไม่ได้ "
                           "(ไม่ได้ผูกกับโรงงานนี้ หรือปิดใช้งานอยู่)")

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
    from app.services.naming import NamingError, clean_part, compose_name
    from app.services.units import normalize_size

    size = normalize_size(size)  # once: the name and the stored size must agree
    try:
        composed_name = compose_name(
            item_name, brand=brand, model=model,
            size=size, detail=variant,
            category_prefix=name_prefix_of(group, sub),
        )
    except NamingError as e:
        raise RequestError(str(e)) from e

    return RequestFields(
        code_system_id=code_system_id,
        group_id=group_id,
        subgroup_id=subgroup_id,
        item_name=composed_name,
        # Cleaned by the same rule compose_name applies to it, so composing
        # from the stored fields gives this Item Name again (until Procurement
        # types a name; a resubmit then recomposes on purpose, STORY-009 Q16).
        # None when it cleans to nothing ("--" with a brand): ask again.
        base_name=clean_part(item_name) or None,
        brand=brand or None,
        model=model or None,
        size=size or None,
        variant=variant or None,
        spec_note=spec_note or None,
        uom=_canonical_uom(db, uom),
        # If the requester left search name blank, classify the BASE name into a
        # canonical category term (dictionary -> master neighbours -> LLM).
        # A resubmit classifies before its claim and passes classify_blank=False,
        # so the LLM is never asked while the row is held.
        search_name=_resolve_search_name(
            db, search_name, item_name, factory_id,
            product_type=(sub or group).product_type,
        ) if classify_blank else (search_name or "").strip()[:60],
        purchase_price=purchase_price or None,
        procurement_category=procurement_category or None,
    )


def _duplicate_line(db: Session, factory_id: int, typed_base: str, brand: str | None,
                    model: str | None) -> str | None:
    """'duplicate candidates: …' with the top 3 Snapshot matches, for a
    `submitted` event; None when nothing matches. Pass the Base Name as the
    form posted it (both submit and resubmit do), so the queries agree."""
    source = snapshots.source_for_factory(db, factory_id)
    query = " ".join(p for p in [typed_base, brand or "", model or ""] if p)
    matches = snapshots.search_similar(db, source=source, query=query, limit=3)
    if not matches:
        return None
    return "duplicate candidates: " + "; ".join(
        f"{i.item_number} {i.name[:60]} ({s:.0%})" for i, s in matches)


# --- Resubmit (STORY-009) -------------------------------------------------------

# Fields a resubmit compares, in the order the change lines list them; the
# labels are the request form's. The category is compared separately.
_RESUBMIT_FIELDS: list[tuple[str, str]] = [
    ("base_name", "ชื่อเรียก"), ("brand", "แบรนด์"), ("model", "รุ่น"), ("size", "ขนาด"),
    ("variant", "ชนิด/สี"), ("uom", "หน่วยนับ"), ("spec_note", "สเปค"),
    ("search_name", "Search name"), ("purchase_price", "ราคาซื้อ"),
    ("procurement_category", "Procurement Category"),
]


def _not_waiting(req: ItemRequest) -> RequestConflict:
    from app.templating import STATUS_LABELS

    return RequestConflict(
        f"คำขอนี้ไม่ได้รอข้อมูลแล้ว (สถานะปัจจุบัน: {STATUS_LABELS.get(req.status, req.status)})")


def _requester_is(req: ItemRequest, email: str) -> bool:
    return normalize_email(req.requester_email) == normalize_email(email)


def _originator_is(req: ItemRequest, email: str) -> bool:
    return bool(req.originator_email) and \
        normalize_email(req.originator_email) == normalize_email(email)


def named_on(req: ItemRequest, email: str) -> bool:
    """The email is the request's Requester or Originator (no Plant or active
    rule: who an event's actor was, e.g. for the queue card)."""
    return _requester_is(req, email) or _originator_is(req, email)


def is_requester(req: ItemRequest, account: Account) -> bool:
    return _requester_is(req, account.email)


def _named_originator(req: ItemRequest, account: Account) -> bool:
    return _originator_is(req, account.email)


def is_originator(req: ItemRequest, account: Account) -> bool:
    """The Account is who the request was made for (and not its Requester)."""
    return not is_requester(req, account) and _named_originator(req, account)


def _may_own(req: ItemRequest, account: Account) -> bool:
    """Requester, or an active Originator in the request's Plant (an Account
    without a Plant, i.e. Procurement or Administrator, in any Plant).
    decisions.md 2026-10-16."""
    if is_requester(req, account):
        return True
    return (_named_originator(req, account) and account.active
            and account.factory_id in (None, req.factory_id))


def may_resubmit(req: ItemRequest, account: Account) -> bool:
    """Whether "My requests" offers this Account the resubmit button."""
    return req.status == "needs_info" and _may_own(req, account)


def resubmittable(db: Session, request_id: int, account: Account) -> ItemRequest:
    """The request, if this Account may resubmit it now; else a RequestError.

    The request's own Requester, whatever their Role, or its Originator (see
    `_may_own`): Procurement that neither submitted it nor asked for it gets
    403 too. Ownership is checked before the status, so a stranger learns
    nothing about the request.
    """
    req = db.get(ItemRequest, request_id)
    if req is None:
        raise RequestNotFound("ไม่พบคำขอนี้")
    if not _may_own(req, account):
        if is_originator(req, account) and account.active:
            # Followed the Needs Info email from another Plant (ticket 04 rule).
            raise RequestForbidden("บัญชีของคุณอยู่คนละโรงงานกับคำขอนี้ จึงแก้ไขในระบบไม่ได้ "
                                   "— ตอบกลับทางอีเมลที่ได้รับแทนได้")
        raise RequestForbidden("แก้ไขและส่งกลับได้เฉพาะคำขอของคุณเอง หรือคำขอที่มีคนขอแทนคุณ")
    if req.status != "needs_info":
        raise _not_waiting(req)
    return req


def originator_editable(req: ItemRequest, account: Account) -> bool:
    """Only the Requester decides who a request is for, and only with a Role
    that may name an originator at all (a Requester-role Account cannot, as on
    a new request)."""
    return is_requester(req, account) and has_role(account, "procurement")


def needs_info_reason(db: Session, req: ItemRequest) -> str | None:
    """What Procurement asked for: the latest needs_info event's note."""
    return db.scalar(
        select(RequestEvent.detail)
        .where(RequestEvent.request_id == req.id, RequestEvent.action == "needs_info")
        .order_by(RequestEvent.id.desc())
        .limit(1)
    )


def _category_label(db: Session, group_id: int, subgroup_id: int | None) -> str:
    group = db.get(CodeGroup, group_id)
    sub = db.get(CodeGroup, subgroup_id) if subgroup_id is not None else None
    return f"{group.code}-{sub.code}" if sub else group.code


def _flat(value: object) -> str:
    """A field value as text on one line, whitespace collapsed; None is ''."""
    return " ".join(str(value).split()) if value is not None else ""


def _shown(value: object) -> str:
    """A field value on one change line: '-' when empty, newlines flattened."""
    return _flat(value) or "-"


def _same(stored: object, posted: object) -> bool:
    """Did the form post back what it was prefilled with? Compared as text with
    whitespace collapsed: a browser drops a textarea's leading newline and
    sends CRLF, and normalising (search name cut to 60, UoM aliases) must not
    turn an untouched field into an edit."""
    return _flat(stored) == _flat(posted)


def _edited(req: ItemRequest, posted: dict[str, object]) -> list[str]:
    """The form fields whose posted value differs from the stored one."""
    edited = [name for name in ("code_system_id", "group_id", "subgroup_id")
              if not _same(getattr(req, name), posted[name])]
    edited += [name for name, _ in _RESUBMIT_FIELDS
               if not _same(getattr(req, name), posted[name])]
    return edited


# One `request_edited` line is "label: old → new". The queue reads the Item
# Name line back for the replaced-name warning (queue_view), so the format
# lives here once.
CHANGE_ARROW = " → "
NAME_CHANGE_LABEL = "ชื่อสินค้า"


def change_line(label: str, old: object, new: object) -> str:
    return f"{label}: {old}{CHANGE_ARROW}{new}"


def _change_lines(db: Session, req: ItemRequest, fields: RequestFields,
                  edited: list[str]) -> list[str]:
    """'label: old → new' for each edited field, the new value as it will be stored."""
    lines = []
    if {"code_system_id", "group_id", "subgroup_id"} & set(edited):
        lines.append(change_line("หมวด", _category_label(db, req.group_id, req.subgroup_id),
                                 _category_label(db, fields.group_id, fields.subgroup_id)))
    lines += [change_line(label, _shown(getattr(req, name)), _shown(getattr(fields, name)))
              for name, label in _RESUBMIT_FIELDS if name in edited]
    return lines


MAX_REPLY_LEN = 1000


def _one_line(text: str | None, what: str) -> str:
    """Required text on one line, NFC + SARA AM fixed (HANDOFF §6.2). One line,
    so a reply cannot add a line below it that looks like a system line of the
    `submitted` event; the text itself may still start with anything.
    `what` names the field in the Thai errors."""
    import unicodedata

    from app.services.snapshots import fix_thai

    text = " ".join(fix_thai(unicodedata.normalize("NFC", text or "")).split())
    if not text:
        raise RequestError(f"กรุณาระบุ{what}")
    if len(text) > MAX_REPLY_LEN:
        raise RequestError(f"{what}ยาวเกิน {MAX_REPLY_LEN} ตัวอักษร")
    return text


def _clean_reply(reply: str | None) -> str:
    return _one_line(reply, "ข้อความตอบจัดซื้อ")


def _claim_from_needs_info(db: Session, request_id: int) -> ItemRequest:
    """Move the request from needs_info to submitted, or raise; the one way out
    of Needs Info (resubmit and Procurement's requeue both use it).

    A conditional UPDATE, the notifier's pattern: of two attempts only one
    changes the row, the other gets 0 rows → RequestConflict (409), or
    RequestNotFound if the row is gone. The row stays locked until the
    caller commits, so the caller writes the rest in the same transaction.
    """
    from sqlalchemy import text

    claimed = db.execute(
        # updated_at by hand: a raw UPDATE skips the ORM's onupdate.
        text("UPDATE item_requests SET status = 'submitted', updated_at = CURRENT_TIMESTAMP "
             "WHERE id = :id AND status = 'needs_info'"),
        {"id": request_id},
    ).rowcount
    db.expire_all()
    if claimed != 1:
        db.rollback()
        current = db.get(ItemRequest, request_id)
        if current is None:
            raise RequestNotFound("ไม่พบคำขอนี้")
        raise _not_waiting(current)
    return db.get(ItemRequest, request_id)


def notifies_procurement(account: Account) -> bool:
    """A resubmit is emailed to Procurement only when someone outside it made
    it: Procurement and Administrators are not told about their own action
    (decisions.md 2026-10-16)."""
    return not has_role(account, "procurement")


@dataclass
class Resubmitted:
    req: ItemRequest
    # The `submitted` event this resubmit wrote, when Procurement must be
    # emailed about it; None otherwise. The id comes from the write itself,
    # never from a later lookup that a status change could overtake.
    notify_event_id: int | None


def requeue_request(db: Session, request_id: int, account: Account,
                    note: str | None) -> ItemRequest:
    """Procurement's "ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่": back to the queue
    without edits, e.g. after a reply by phone. The note is required (Q5) and
    becomes the `submitted` event's detail; the Needs Info note is cleared
    (Q20). No email (Q18). Procurement or Administrator only, checked here and
    not just by the queue router, as every rule lives in the service."""
    if not has_role(account, "procurement"):
        raise RequestForbidden("รับเข้าคิวใหม่ได้เฉพาะฝ่ายจัดซื้อ — ผู้ขอใช้ 'แก้ไขและส่งกลับ'")
    note = _one_line(note, "หมายเหตุว่าผู้ขอแจ้งอะไรมา")
    req = _claim_from_needs_info(db, request_id)
    req.review_note = None
    db.add(RequestEvent(request_id=req.id, actor=account.email, action="submitted",
                        detail=note))
    db.commit()
    return req


def resubmit_request(
    db: Session,
    request_id: int,
    account: Account,
    *,
    reply: str,
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
) -> "Resubmitted":
    """The Requester or Originator answers Needs Info: edit the fields, send it back.

    Plant is always the stored one. The row is claimed first with a
    conditional UPDATE (needs_info → submitted, the notifier's pattern), so of
    two attempts only one gets the row; then the fields are checked and saved
    in that same transaction, and any refusal rolls the claim back. Nothing
    slow happens under the claim: a blank Search name (which may ask the LLM)
    is worked out before it. A field counts as edited only if the posted text
    differs from the stored one; with no edit the request keeps its Item Name,
    even one Procurement typed. Otherwise the name is recomposed. The
    originator fields are ignored unless `originator_editable`; a change to
    them is checked as on a new request.
    """
    req = resubmittable(db, request_id, account)
    reply = _clean_reply(reply)
    # Required even when nothing else changed: an old row has no Base Name
    # yet, and an empty one posted back would otherwise count as "unchanged".
    _require_base_name(item_name)
    # What was edited is judged on the posted Search name: clearing it is an
    # edit, whatever the classifier then suggests.
    posted_search_name = search_name
    # A new Base Name with the Search name left as it was: work out a new one,
    # as for a new request (Peter, 2026-10-16), or "Hydraulic Hose" would keep
    # "BEARING". A Search name the Requester typed is kept.
    refresh_search_name = not _same(req.base_name, item_name) and \
        _same(req.search_name, search_name)
    if refresh_search_name:
        search_name = None
    if not (search_name or "").strip() and item_name.strip():
        chosen = (db.get(CodeGroup, subgroup_id) if subgroup_id is not None else None) \
            or db.get(CodeGroup, group_id)
        search_name = _resolve_search_name(
            db, None, item_name, req.factory_id,
            product_type=chosen.product_type if chosen else None)
    # The fuzzy search over the snapshot is slow too: before the claim, not
    # under it. The Plant never changes on a resubmit.
    duplicates = _duplicate_line(db, req.factory_id, item_name, brand, model)
    db.rollback()  # end the read-only transaction: the claim starts a fresh one
    req = _claim_from_needs_info(db, request_id)

    posted = {
        "code_system_id": code_system_id, "group_id": group_id, "subgroup_id": subgroup_id,
        "base_name": item_name, "brand": brand, "model": model, "size": size,
        "variant": variant, "spec_note": spec_note, "uom": uom,
        "search_name": posted_search_name,
        "purchase_price": purchase_price, "procurement_category": procurement_category,
    }
    edited = _edited(req, posted)
    if refresh_search_name and "search_name" not in edited:
        edited.append("search_name")  # so its change line is logged
    # A field not posted at all (None) keeps its value; only "" clears it.
    if on_behalf_of is None:
        on_behalf_of = req.originator_name
    if originator_email is None:
        originator_email = req.originator_email
    originator_changes = []
    if originator_editable(req, account) and not (
            _same(req.originator_name, on_behalf_of)
            and _same(req.originator_email, originator_email)):
        try:
            name, email = _check_originator(db, on_behalf_of, originator_email,
                                            keep_email=req.originator_email)
        except RequestError:
            db.rollback()  # back to needs_info, nothing written
            raise
        for label, attr, value in (("ขอแทน", "originator_name", name),
                                   ("อีเมลผู้ขอจริง", "originator_email", email)):
            if getattr(req, attr) != value:
                originator_changes.append(
                    change_line(label, _shown(getattr(req, attr)), _shown(value)))
                setattr(req, attr, value)
    changes = []
    if edited:
        try:
            fields = _validated_fields(
                db, req.factory_id, code_system_id=code_system_id, group_id=group_id,
                subgroup_id=subgroup_id, item_name=item_name, brand=brand, model=model,
                size=size, variant=variant, spec_note=spec_note, uom=uom,
                search_name=search_name, purchase_price=purchase_price,
                procurement_category=procurement_category, classify_blank=False,
            )
        except RequestError:
            db.rollback()  # back to needs_info, nothing written
            raise
        changes = _change_lines(db, req, fields, edited)
        if fields.item_name != req.item_name:
            changes.append(change_line(NAME_CHANGE_LABEL, req.item_name, fields.item_name))
        for name, value in asdict(fields).items():
            setattr(req, name, value)
    changes += originator_changes  # last, so the field lines keep one order
    if changes:
        db.add(RequestEvent(request_id=req.id, actor=account.email, action="request_edited",
                            detail="\n".join(changes)))
    req.review_note = None
    lines = [reply]
    if duplicates:
        lines.append(duplicates)
    submitted = RequestEvent(request_id=req.id, actor=account.email, action="submitted",
                             detail="\n".join(lines))
    db.add(submitted)
    db.commit()
    return Resubmitted(req=req, notify_event_id=submitted.id
                       if notifies_procurement(account) else None)


def change_status(
    db: Session, request_id: int, *, new_status: str, account: Account,
    note: str | None = None,
) -> ItemRequest:
    # Approval mints a code from the register: Administrator only.
    if new_status == "approved":
        _require_administrator(account)
    if new_status == "submitted":
        # The only way back to submitted is out of Needs Info, and that has
        # one path with its own claim and rules (STORY-009 ticket 03).
        return requeue_request(db, request_id, account, note)
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
    """The Account's own requests and those made on its behalf, newest first
    ("My requests"), in every status.

    No Plant or active rule here, unlike `may_resubmit`: the Originator already
    gets the same data by email, and hiding the row would leave "an email but
    no request to find" (Peter, 2026-10-19). The row is read-only for them.

    Matched on email, which never changes for an Account. Compared without case
    or surrounding spaces, since requests typed in before login existed may
    carry the address as the person wrote it.
    """
    me = account.email.lower()
    return list(db.scalars(
        select(ItemRequest)
        .where(or_(func.lower(func.trim(ItemRequest.requester_email)) == me,
                   func.lower(func.trim(ItemRequest.originator_email)) == me))
        .order_by(ItemRequest.created_at.desc(), ItemRequest.id.desc())
    ))


def list_queue(db: Session, status: str | None = None) -> list[ItemRequest]:
    stmt = select(ItemRequest).order_by(ItemRequest.created_at.desc())
    if status:
        stmt = stmt.where(ItemRequest.status == status)
    return list(db.scalars(stmt))
