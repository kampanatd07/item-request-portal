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

from app.models import ItemRequest, ItemSnapshot, RunningRegister
from app.services.snapshots import source_for_factory

RUN_RE = re.compile(r"\{run:(\d+)\}")


class CodegenError(Exception):
    """Domain error with a user-facing Thai message."""


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


def _allocate_from_register(db: Session, group_code: str, sub_code: str) -> int:
    """Issue the next number for a Category+Sub pair from the central register.

    This is the single place a central code may come from. The row is locked
    for update so two approvals in the same second cannot take the same number;
    the unique constraint on generated_code is the last line of defence.
    """
    stmt = select(RunningRegister).where(
        RunningRegister.group_code == group_code,
        RunningRegister.sub_code == sub_code,
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    reg = db.scalar(stmt)
    if reg is None:
        # A sub-category that exists in the taxonomy but not yet in the
        # register (new sub-category added later) starts its own series.
        reg = RunningRegister(group_code=group_code, sub_code=sub_code, last_running=0)
        db.add(reg)
        db.flush()
    reg.last_running += 1
    db.flush()
    return reg.last_running


def generate_code(db: Session, request: ItemRequest) -> str:
    system_code = request.code_system.code
    if system_code == "CENTRAL":
        group = request.group
        sub = request.subgroup
        if sub is None:
            raise CodegenError("ต้องเลือกหมวดย่อยก่อนออกรหัสกลาง")
        running = _allocate_from_register(db, group.code, sub.code)
        if running > 9999:
            raise CodegenError(
                f"เลขรันของหมวด {group.code}-{sub.code} เต็มแล้ว (เกิน 9999) — "
                "ต้องเปิดหมวดย่อยใหม่"
            )
        # [Group 3][Sub 2][Item Type 2 = 00][Running 4]
        return f"{group.code}{sub.code}00{running:04d}"

    # Legacy systems (inactive today, kept for the future stock scope).
    prefix, run_len = build_prefix_and_runlen(request)
    source = source_for_factory(db, request.factory_id)
    running = next_running(db, source=source, prefix=prefix, run_len=run_len)
    if running >= 10 ** run_len:
        raise CodegenError(
            f"เลข running ของกลุ่ม {prefix} เต็มแล้ว (เกิน {run_len} หลัก)"
        )
    return f"{prefix}{running:0{run_len}d}"
