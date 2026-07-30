"""Standard item-name composition (แบบ B — company convention).

The product name is COMPOSED from structured fields, never free-typed:
    ชื่อเรียกสินค้า -> แบรนด์ -> รุ่น -> ขนาด -> รายละเอียด(ชนิด/สี)
e.g.  Ball Bearing SKF 6205-2Z 25mm

Cleaning applied while composing:
- trim + collapse whitespace in every part
- drop a part that merely repeats an earlier token (user typed brand in the
  name field too -> no 'SKF SKF')
- strip characters that break AX imports or Excel formulas (=, |, tabs)
- length guard (AX name columns)

Requesters cannot edit the composed result; procurement can override at
review, and the override is audit-logged.
"""

import re

MAX_NAME_LEN = 100

_FORBIDDEN = re.compile(r"[=|\t\r\n]")


class NamingError(Exception):
    """User-facing Thai message."""


def _clean_part(part: str | None) -> str:
    part = _FORBIDDEN.sub(" ", part or "")
    return " ".join(part.split())


def compose_name(
    base: str,
    brand: str | None = None,
    model: str | None = None,
    size: str | None = None,
    detail: str | None = None,
) -> str:
    """Join parts in convention order, skipping repeats and noise."""
    parts: list[str] = []
    seen: set[str] = set()
    for raw in [base, brand, model, size, detail]:
        cleaned = _clean_part(raw)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        # drop the part if every one of its tokens already appeared
        tokens = [t.lower() for t in cleaned.split()]
        if tokens and all(t in seen for t in tokens):
            continue
        parts.append(cleaned)
        seen.add(key)
        seen.update(tokens)

    name = " ".join(parts)
    if not name:
        raise NamingError("กรุณากรอกชื่อเรียกสินค้า")
    if len(name) > MAX_NAME_LEN:
        raise NamingError(
            f"ชื่อที่ประกอบได้ยาว {len(name)} ตัวอักษร (เกิน {MAX_NAME_LEN}) — "
            "ย้ายรายละเอียดปลีกย่อยไปช่องสเปคเพิ่มเติม"
        )
    return name
