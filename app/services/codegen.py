"""Item code generation.

Patterns are data, not code: each code system stores a pattern_template
(e.g. '9905{cat}{sub}{run:4}'), and a group may override it
(e.g. SVSP -> '64{cat}{run:4}', Mould 806 -> '{group}{sub}{run:5}').

Template placeholders:
  {group} -> group code            {cat} -> group code (alias)
  {sub}   -> subgroup code         {run:N} -> N-digit running number

Next running = max(existing) + 1 where existing = item snapshot codes with the
same prefix/shape UNION codes already generated for pending requests. Never
count-based: real data has gaps (e.g. 64IT has 650 rows but max 6613).
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RETIRE_REASONS, ItemRequest, ItemSnapshot, RetiredCode, RunningRegister
from app.services.snapshots import source_for_factory

RUN_RE = re.compile(r"\{run:(\d+)\}")


class CodegenError(Exception):
    """Domain error with a user-facing Thai message."""


def is_retired(db: Session, code: str) -> bool:
    """True if `code` was issued once and thrown away (never usable again),
    including one retired earlier in this still-open transaction."""
    if any(isinstance(o, RetiredCode) and o.code == code for o in db.new):
        return True
    # No autoflush: the caller may hold unflushed changes (e.g. a new code on the
    # request) whose own errors must surface at the caller's commit, not here.
    with db.no_autoflush:
        return db.scalar(select(RetiredCode.id).where(RetiredCode.code == code)) is not None


def retire_code(db: Session, code: str, *, request_id: int | None, reason: str,
                actor: str) -> RetiredCode:
    """Record that an issued Central Code is thrown away for good.

    The only writer of retired_codes. Adds to the caller's session without
    committing, so it lands in the same transaction as the change that burned
    the number; the unique constraint on `code` backs this check up at commit.
    """
    if reason not in RETIRE_REASONS:
        raise ValueError(f"unknown retire reason: {reason}")
    if is_retired(db, code):
        raise CodegenError(f"รหัส {code} ถูกทิ้งไปแล้ว — ใช้ซ้ำไม่ได้")
    retired = RetiredCode(code=code, request_id=request_id, reason=reason, actor=actor)
    db.add(retired)
    return retired


def build_prefix_and_runlen(request: ItemRequest) -> tuple[str, int]:
    template = (
        request.group.pattern_override or request.code_system.pattern_template
    )
    m = RUN_RE.search(template)
    if m is None:
        raise CodegenError(
            f"pattern ของระบบไม่ถูกต้อง (ไม่มี run): {template}"
        )
    run_len = int(m.group(1))
    prefix = template[: m.start()]
    if template[m.end():]:
        raise CodegenError("pattern ต้องจบด้วย {run:N}")

    if "{sub}" in prefix and request.subgroup is None:
        raise CodegenError("หมวดนี้ต้องมีหมวดย่อยก่อนออกรหัส")
    values = {
        "group": request.group.code,
        "cat": request.group.code,
        "sub": request.subgroup.code if request.subgroup else "",
    }
    try:
        prefix = prefix.format(**values)
    except (KeyError, IndexError) as exc:
        raise CodegenError(f"pattern มี placeholder ที่ไม่รู้จัก: {exc}") from exc
    if not prefix:
        raise CodegenError("prefix ว่าง — ตรวจ pattern ของระบบ")
    return prefix, run_len


def next_running(db: Session, *, source: str, prefix: str, run_len: int) -> int:
    """Scan snapshot + already-generated request codes for prefix + exactly
    run_len digits; return max+1 (1 if none)."""
    total_len = len(prefix) + run_len
    best = 0

    snapshot_codes = db.scalars(
        select(ItemSnapshot.item_number).where(
            ItemSnapshot.source == source,
            ItemSnapshot.item_number.like(f"{prefix}%"),
        )
    )
    request_codes = db.scalars(
        select(ItemRequest.generated_code).where(
            ItemRequest.generated_code.like(f"{prefix}%")
        )
    )
    for code in list(snapshot_codes) + list(request_codes):
        code = (code or "").strip()
        if len(code) != total_len:
            continue
        suffix = code[len(prefix):]
        if suffix.isdigit():
            best = max(best, int(suffix))
    return best + 1


def central_code(group_code: str, sub_code: str, running: int) -> str:
    """[Group 3][Sub 2][Item Type 2 = 00][Running 4]"""
    return f"{group_code}{sub_code}00{running:04d}"


def lock_register(db: Session, group_code: str, sub_code: str) -> RunningRegister:
    """The register row for a Category+Sub pair, locked until commit (Postgres).

    Lock order everywhere is request row first (requests._get_locked), then
    this register row, so Approval, re-issue and override cannot deadlock.
    """
    stmt = select(RunningRegister).where(
        RunningRegister.group_code == group_code,
        RunningRegister.sub_code == sub_code,
    ).with_for_update().execution_options(populate_existing=True)
    reg = db.scalar(stmt)
    if reg is None:
        # A sub-category that exists in the taxonomy but not yet in the
        # register (new sub-category added later) starts its own series.
        reg = RunningRegister(group_code=group_code, sub_code=sub_code, last_running=0)
        db.add(reg)
        db.flush()
    return reg


def retired_among(db: Session, codes) -> set[str]:
    """Which of `codes` are Retired Codes — one query per 500, for a whole range."""
    codes = list(codes)
    found = {o.code for o in db.new if isinstance(o, RetiredCode) and o.code in set(codes)}
    with db.no_autoflush:
        for i in range(0, len(codes), 500):
            found.update(db.scalars(select(RetiredCode.code)
                                    .where(RetiredCode.code.in_(codes[i:i + 500]))))
    return found


def on_requests_among(db: Session, codes) -> set[str]:
    """Which of `codes` some request carries — one query per 500."""
    codes = list(codes)
    found: set[str] = set()
    with db.no_autoflush:
        for i in range(0, len(codes), 500):
            found.update(db.scalars(select(ItemRequest.generated_code)
                                    .where(ItemRequest.generated_code.in_(codes[i:i + 500]))))
    return found


def retire_many(db: Session, codes: list[str], *, request_id: int | None, reason: str,
                actor: str) -> None:
    """retire_code for a whole range (numbers skipped by a register jump), checked
    with one query instead of one per number, so a big confirmed jump stays fast
    while the request and register rows are locked."""
    if reason not in RETIRE_REASONS:
        raise ValueError(f"unknown retire reason: {reason}")
    already = retired_among(db, codes)
    if already:
        raise CodegenError(f"รหัส {sorted(already)[0]} ถูกทิ้งไปแล้ว — ใช้ซ้ำไม่ได้")
    db.add_all(RetiredCode(code=c, request_id=request_id, reason=reason, actor=actor)
               for c in codes)


def code_on_request(db: Session, code: str, *, other_than: int | None = None) -> bool:
    """True if a request (other than `other_than`) carries `code`."""
    stmt = select(ItemRequest.id).where(ItemRequest.generated_code == code)
    if other_than is not None:
        stmt = stmt.where(ItemRequest.id != other_than)
    with db.no_autoflush:
        return db.scalar(stmt) is not None


def master_loaded(db: Session) -> bool:
    """Whether the classified master (the group's Central Codes) is uploaded."""
    return db.scalar(select(ItemSnapshot.id).where(ItemSnapshot.source == "CENTRAL")
                     .limit(1)) is not None


def master_codes(db: Session, codes) -> dict[str, str]:
    """Which of `codes` the group master holds, mapped to their item names."""
    codes = list(codes)
    found: dict[str, str] = {}
    for i in range(0, len(codes), 500):  # keep the IN list small
        for number, name in db.execute(
            select(ItemSnapshot.item_number, ItemSnapshot.name).where(
                ItemSnapshot.source == "CENTRAL",
                ItemSnapshot.item_number.in_(codes[i:i + 500]))):
            found[number] = name
    return found


def _allocate_from_register(db: Session, group_code: str, sub_code: str) -> int:
    """Issue the next number for a Category+Sub pair from the central register.

    This is the single place a central code may come from. Before taking the
    number it checks that nobody holds it already — a Retired Code, another
    request, or the group master. If someone does, the register is behind:
    refuse, never skip ahead silently, and leave the register as it was.
    """
    reg = lock_register(db, group_code, sub_code)
    running = reg.last_running + 1
    if running > 9999:
        raise CodegenError(
            f"เลขรันของหมวด {group_code}-{sub_code} เต็มแล้ว (เกิน 9999) — "
            "ต้องเปิดหมวดย่อยใหม่"
        )
    code = central_code(group_code, sub_code, running)
    if is_retired(db, code) or code_on_request(db, code) or master_codes(db, [code]):
        raise CodegenError(
            f"ออกรหัสไม่ได้: เลขถัดไปของหมวด {group_code}-{sub_code} ({code}) "
            "ถูกใช้หรือถูกทิ้งไปแล้ว — Running Register ของหมวดนี้ตามหลัง "
            "ให้ผู้ดูแลระบบตรวจว่ามีรหัสถูกออกนอก portal หรือไม่ (STORY-005)"
        )
    reg.last_running = running
    db.flush()
    return running


def generate_code(db: Session, request: ItemRequest) -> str:
    system_code = request.code_system.code
    if system_code == "CENTRAL":
        group = request.group
        sub = request.subgroup
        if sub is None:
            raise CodegenError("ต้องเลือกหมวดย่อยก่อนออกรหัสกลาง")
        running = _allocate_from_register(db, group.code, sub.code)
        return central_code(group.code, sub.code, running)

    # Legacy systems (inactive today, kept for the future stock scope).
    prefix, run_len = build_prefix_and_runlen(request)
    source = source_for_factory(db, request.factory_id)
    running = next_running(db, source=source, prefix=prefix, run_len=run_len)
    if running >= 10 ** run_len:
        raise CodegenError(
            f"เลข running ของกลุ่ม {prefix} เต็มแล้ว (เกิน {run_len} หลัก)"
        )
    return f"{prefix}{running:0{run_len}d}"
