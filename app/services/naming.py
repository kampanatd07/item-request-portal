"""Standard item-name composition — Carabao Group convention (approved Aug 2026).

    [CATEGORY] - [ชื่อสินค้า/บริการ] - [รายละเอียดจำเพาะ]      <= 110 chars

  CATEGORY   the sub-category's Name Prefix, English, upper case  (<= 16)
  ชื่อ        noun first, then brand/model                        (<= 50)
  รายละเอียด  size / spec / material / packing                     (<= 40)

Mandatory rules enforced here (docs/rules/naming-standard.md):
1. ' - ' is the only level separator; '--', ':', '/', ',' are rejected
2. a name may not start with a separator or punctuation
3. noun before modifier (enforced by field order, not by parsing)
4. number and unit are separated by one space ('20 L', not '20L')
5. '(ยกเลิก)' is never part of a name — use Lifecycle State = Blocked
6. no price, vendor, PO number or project name inside the name

Requesters cannot edit the composed result; procurement can override at
review, and the override is audit-logged.
"""

import re

MAX_NAME_LEN = 110
MAX_CATEGORY_LEN = 16
MAX_BASE_LEN = 50
MAX_DETAIL_LEN = 40

_FORBIDDEN = re.compile(r"[=|\t\r\n]")
# separators that must not appear as level separators inside a segment
_BAD_SEPARATORS = re.compile(r"--+|\s:\s|\s/\s|\s,\s")
_BLOCKED_WORDS = re.compile(r"\(\s*ยกเลิก\s*\)", re.IGNORECASE)


class NamingError(Exception):
    """User-facing Thai message."""


def clean_part(part: str | None) -> str:
    """One name part, cleaned as `compose_name` cleans every part."""
    part = _FORBIDDEN.sub(" ", part or "")
    part = _BAD_SEPARATORS.sub(" ", part)
    part = _BLOCKED_WORDS.sub("", part)
    part = " ".join(part.split())
    # rule 2: never begin with punctuation
    return part.lstrip("-–—:/,. ").strip()


def _join_unique(parts: list[str]) -> str:
    """Join with single spaces, dropping parts whose tokens all already appeared."""
    out: list[str] = []
    seen: set[str] = set()
    for cleaned in parts:
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        tokens = [t.lower() for t in cleaned.split()]
        if tokens and all(t in seen for t in tokens):
            continue
        out.append(cleaned)
        seen.add(key)
        seen.update(tokens)
    return " ".join(out)


def compose_name(
    base: str,
    brand: str | None = None,
    model: str | None = None,
    size: str | None = None,
    detail: str | None = None,
    category_prefix: str | None = None,
) -> str:
    """Build '[CATEGORY] - [name] - [detail]' per the group naming standard.

    category_prefix comes from the chosen sub-category (taxonomy Name Prefix).
    When it is absent the name degrades gracefully to the two remaining
    segments rather than emitting a dangling separator.
    """
    category = clean_part(category_prefix).upper()[:MAX_CATEGORY_LEN]
    name_seg = _join_unique([clean_part(base), clean_part(brand), clean_part(model)])
    detail_seg = _join_unique([clean_part(size), clean_part(detail)])

    if not name_seg:
        raise NamingError("กรุณากรอกชื่อเรียกสินค้า")
    if len(name_seg) > MAX_BASE_LEN:
        raise NamingError(
            f"ชื่อสินค้ายาว {len(name_seg)} ตัวอักษร (เกิน {MAX_BASE_LEN}) — "
            "ย้ายรายละเอียดไปช่องขนาด/ชนิด หรือสเปคเพิ่มเติม"
        )
    if len(detail_seg) > MAX_DETAIL_LEN:
        raise NamingError(
            f"รายละเอียดจำเพาะยาว {len(detail_seg)} ตัวอักษร (เกิน {MAX_DETAIL_LEN}) — "
            "ย้ายส่วนเกินไปช่องสเปคเพิ่มเติม"
        )

    name = " - ".join(seg for seg in [category, name_seg, detail_seg] if seg)
    if len(name) > MAX_NAME_LEN:
        raise NamingError(
            f"ชื่อที่ประกอบได้ยาว {len(name)} ตัวอักษร (เกิน {MAX_NAME_LEN})"
        )
    return name
