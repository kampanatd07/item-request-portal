"""Item-master snapshot: import + duplicate search.

Search is implemented portably (token prefilter in SQL + trigram scoring in
Python) so it runs identically on SQLite (dev/tests) and Postgres. If volume
grows or latency hurts, swap the internals for pg_trgm — callers won't change.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from openpyxl import load_workbook
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    CodeGroup,
    CodeSystem,
    Factory,
    ItemSnapshot,
    RunningRegister,
    SnapshotImport,
)
from app.services.naming import searchable_part

SOURCES = ("CBD", "D365", "CENTRAL")


class SnapshotError(Exception):
    """Import error with a user-facing Thai message."""


def fix_thai(text: str) -> str:
    """Recompose SARA AM. Some sources store it decomposed (NIKHAHIT + SARA AA),
    which makes 'น้ำยา' and 'น้ํายา' compare as different strings."""
    return text.replace("ํา", "ำ")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/spacing noise so 'BALL-BEARING  SKF' == 'ball bearing skf'.

    NFC, never NFKC: NFKC decomposes Thai SARA AM (ำ) into two characters, so
    Thai keywords stop matching entirely.
    """
    text = fix_thai(unicodedata.normalize("NFC", text or ""))
    text = text.lower()
    text = re.sub(r"[^\w฀-๿]+", " ", text)  # keep Thai + word chars
    return " ".join(text.split())


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of character trigrams — same idea as pg_trgm."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ASCII digits only: \d and str.isdigit() also accept Thai numerals (๐-๙) and
# fullwidth digits, which would store a "code" that never equals a real one.
CENTRAL_CODE = re.compile(r"[0-9]{11}")
ASCII_DIGITS = re.compile(r"[0-9]+")
MAX_LISTED_INVALID = 10


@dataclass
class InvalidRow:
    row: int          # sheet row number, as Excel shows it
    item_number: str
    reason: str       # Thai, for the Administrator
    # "code": not a valid Central Code; "category": a valid code in a
    # Sub-Category the portal's taxonomy does not have (STORY-013).
    kind: str = "code"


@dataclass
class LabeledCheck:
    """What a classified master holds, before anything is written."""

    total: int                                   # non-empty data rows
    valid: list[dict] = field(default_factory=list)
    skipped: int = 0                             # no Item Number yet (pending)
    invalid: list[InvalidRow] = field(default_factory=list)


@dataclass
class RegisterLag:
    """A Group + Sub-Category where the group master is ahead of the register."""

    group_code: str
    sub_code: str
    register: int
    master: int

    @property
    def gap(self) -> int:
        return self.master - self.register


def _cell_text(value) -> str:
    """Cell as text; a code typed as an Excel number reads the same as text."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _code_problem(number: str, name: str, group: str, sub: str) -> str | None:
    """Why a coded row is not a valid Central Code for its own category, or None."""
    if not group or not sub:
        return "ไม่มี Category Code / Sub-Category Code"
    if not name:
        return "ไม่มี Product Name"
    if not (ASCII_DIGITS.fullmatch(group) and len(group) == 3
            and ASCII_DIGITS.fullmatch(sub) and len(sub) == 2):
        return f"Category Code {group} / Sub-Category Code {sub} ไม่ถูกต้อง"
    if not CENTRAL_CODE.fullmatch(number):
        return "ไม่ใช่ตัวเลข 11 หลัก"
    if number[:3] != group:
        return f"หลัก 1–3 ({number[:3]}) ไม่ตรงกับ Category Code {group}"
    if number[3:5] != sub:
        return f"หลัก 4–5 ({number[3:5]}) ไม่ตรงกับ Sub-Category Code {sub}"
    if number[5:7] != "00":
        return f"หลัก 6–7 ต้องเป็น 00 (พบ {number[5:7]})"
    return None


def check_labeled_master(
    filename: str, data: bytes,
    prefixes: dict[tuple[str, str], str | None] | None = None,
) -> LabeledCheck:
    """Read the classified master (New_Item_Master) without writing anything.

    Its Item Number is the group's Central Code, which code override trusts
    (STORY-010), so a coded row must be a valid code for its own Category /
    Sub-Category. Rows with no Item Number are pending group decisions and are
    skipped. Product Name carries the 'CATEGORY - ' prefix; the searchable text
    is the part a user would actually type, so the prefix is cut off by the
    one Name Prefix rule (STORY-013): only the row's own Sub-Category prefix
    (`prefixes`, keyed by (group, sub)), never "whatever is before the first
    ' - '". With `prefixes`, a row whose Sub-Category is not among them is
    invalid: its prefix could not be cut, and its code cannot be issued or
    overridden in the portal either. Without `prefixes` (code checks only)
    nothing is cut and no Sub-Category is refused.
    """
    known = prefixes or {}

    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise SnapshotError("ไฟล์ master ที่จัดหมวดแล้วต้องเป็น .xlsx")
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    required = {"item number", "product name", "category code", "sub-category code"}
    try:
        for ws in wb.worksheets:
            header: dict[str, int] | None = None
            check = LabeledCheck(total=0)
            for row_no, row in enumerate(ws.iter_rows(values_only=True), start=1):
                cells = [_cell_text(c) for c in row]
                if header is None:
                    lowered = [c.lower() for c in cells]
                    if required.issubset(set(lowered)):
                        header = {k: lowered.index(k) for k in required}
                    continue
                if not any(cells):
                    continue
                check.total += 1

                def cell(key: str) -> str:
                    i = header[key]
                    return cells[i] if i < len(cells) else ""

                number, name = cell("item number"), cell("product name")
                group, sub = cell("category code"), cell("sub-category code")
                if not number:
                    check.skipped += 1
                    continue
                group, sub = group.zfill(3) if group else "", sub.zfill(2) if sub else ""
                problem = _code_problem(number, name, group, sub)
                if problem:
                    check.invalid.append(InvalidRow(row_no, number, problem))
                    continue
                if prefixes is not None and (group, sub) not in known:
                    check.invalid.append(InvalidRow(
                        row_no, number, f"หมวด {group}-{sub} ไม่มีใน taxonomy ของระบบ — "
                        "อัปเดต taxonomy ของระบบก่อนอัปโหลด", kind="category"))
                    continue
                searchable = searchable_part(name, known.get((group, sub)))
                check.valid.append({
                    "item_number": number, "name": name, "searchable": searchable,
                    "group_code": group, "sub_code": sub,
                })
            if header is not None:
                return check
    finally:
        wb.close()
    raise SnapshotError(
        "ไม่พบคอลัมน์ Item Number / Product Name / Category Code / Sub-Category Code"
    )


def _invalid_message(invalid: list[InvalidRow]) -> str:
    listed = "; ".join(f"แถว {r.row}: {r.item_number} ({r.reason})"
                       for r in invalid[:MAX_LISTED_INVALID])
    more = len(invalid) - MAX_LISTED_INVALID
    # Counted apart: a row in an unknown Sub-Category has a valid code.
    found = []
    codes = sum(1 for r in invalid if r.kind == "code")
    categories = len(invalid) - codes
    if codes:
        found.append(f"พบรหัสที่ไม่ใช่ Central Code ที่ถูกต้อง {codes} แถว")
    if categories:
        found.append(f"พบหมวดที่ระบบไม่รู้จัก {categories} แถว")
    return (f"ไม่นำเข้าทั้งไฟล์ — {' และ'.join(found)}: "
            f"{listed}" + (f" และอีก {more} แถว" if more > 0 else ""))


def register_lag(db: Session, item_numbers) -> list[RegisterLag]:
    """Group + Sub-Categories whose highest running number in `item_numbers` is
    above the portal's register — the group issued codes the register does not
    know, so the next Approval there would clash (fix via STORY-005). Read-only.
    """
    highest: dict[tuple[str, str], int] = {}
    for number in item_numbers:
        if CENTRAL_CODE.fullmatch(number or ""):
            key = (number[:3], number[3:5])
            highest[key] = max(highest.get(key, 0), int(number[7:]))
    registers = {(r.group_code, r.sub_code): r.last_running
                 for r in db.scalars(select(RunningRegister))}
    lags = [RegisterLag(g, s, registers.get((g, s), 0), top)
            for (g, s), top in highest.items() if top > registers.get((g, s), 0)]
    return sorted(lags, key=lambda lag: (lag.group_code, lag.sub_code))


def central_register_lag(db: Session) -> list[RegisterLag]:
    """register_lag for the classified master currently loaded."""
    return register_lag(db, db.scalars(
        select(ItemSnapshot.item_number).where(ItemSnapshot.source == "CENTRAL")))


def central_prefixes(db: Session) -> dict[tuple[str, str], str | None]:
    """(group code, sub code) → Name Prefix of the central taxonomy: Item
    Groups (top level) and their Sub-Categories only."""
    parent = aliased(CodeGroup)
    rows = db.execute(
        select(parent.code, CodeGroup.code, CodeGroup.name_prefix)
        .join(parent, CodeGroup.parent_id == parent.id)
        .join(CodeSystem, CodeSystem.id == CodeGroup.code_system_id)
        .where(CodeSystem.code == "CENTRAL", parent.parent_id.is_(None))
    )
    return {(g, s): prefix for g, s, prefix in rows}


def import_labeled_master(
    db: Session, *, filename: str, data: bytes, uploaded_by: str
) -> SnapshotImport:
    """Load the classified master: the group's Central Codes (trusted by code
    override) and labelled training data for category suggestion.

    Any coded row that is not a valid Central Code rejects the whole file and
    the previous CENTRAL load stays. Replaces the previous CENTRAL load;
    LEARNED rows are untouched. Never touches the register.
    """
    check = check_labeled_master(filename, data, central_prefixes(db))
    if check.invalid:
        raise SnapshotError(_invalid_message(check.invalid))
    if not check.valid:
        raise SnapshotError("ไม่พบข้อมูลรายการในไฟล์")
    rows = check.valid
    imp = SnapshotImport(
        source="CENTRAL", filename=filename, row_count=len(rows), uploaded_by=uploaded_by
    )
    db.add(imp)
    db.flush()
    db.execute(delete(ItemSnapshot).where(ItemSnapshot.source == "CENTRAL"))
    db.add_all(
        ItemSnapshot(
            source="CENTRAL", item_number=r["item_number"], name=r["name"],
            normalized_name=normalize(r["searchable"]),
            group_code=r["group_code"], sub_code=r["sub_code"], import_id=imp.id,
        )
        for r in rows
    )
    db.commit()
    return imp


def _extract_rows(filename: str, data: bytes) -> list[tuple[str, str, str | None]]:
    """Return (item_number, name, item_group) rows from xlsx/csv.
    Header row must contain 'Item number' and 'Product name' (case-insensitive)."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        # Real master files put documentation sheets first — take the first
        # sheet whose top rows contain the expected header.
        rows_iter = None
        for ws in wb.worksheets:
            for row in ws.iter_rows(max_row=10, values_only=True):
                lowered = [str(c).strip().lower() for c in row if c is not None]
                if "item number" in lowered and "product name" in lowered:
                    rows_iter = ws.iter_rows(values_only=True)
                    break
            if rows_iter is not None:
                break
        if rows_iter is None:
            raise SnapshotError(
                "ไม่พบหัวตาราง 'Item number' และ 'Product name' ในไฟล์"
            )
    elif filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        rows_iter = iter(list(csv.reader(io.StringIO(text))))
    else:
        raise SnapshotError("รองรับเฉพาะไฟล์ .xlsx หรือ .csv")

    header: dict[str, int] | None = None
    out: list[tuple[str, str, str | None]] = []
    for raw in rows_iter:
        cells = ["" if c is None else str(c).strip() for c in raw]
        if header is None:
            lowered = [c.lower() for c in cells]
            if "item number" in lowered and "product name" in lowered:
                header = {
                    "number": lowered.index("item number"),
                    "name": lowered.index("product name"),
                    "group": lowered.index("item group") if "item group" in lowered else -1,
                }
            continue
        number = cells[header["number"]] if header["number"] < len(cells) else ""
        name = cells[header["name"]] if header["name"] < len(cells) else ""
        if not number or not name:
            continue
        group = (
            cells[header["group"]]
            if header["group"] >= 0 and header["group"] < len(cells)
            else None
        )
        out.append((number, name, group or None))
    if header is None:
        raise SnapshotError(
            "ไม่พบหัวตาราง 'Item number' และ 'Product name' ในไฟล์"
        )
    if not out:
        raise SnapshotError("ไฟล์ไม่มีข้อมูลรายการสินค้า")
    return out


def import_snapshot(
    db: Session, *, source: str, filename: str, data: bytes, uploaded_by: str
) -> SnapshotImport:
    # CENTRAL is the group's list of Central Codes that override trusts; it may
    # only arrive through import_labeled_master, which validates every code.
    if source not in SOURCES or source == "CENTRAL":
        raise SnapshotError("แหล่งข้อมูลไม่ถูกต้อง (CBD หรือ D365)")
    rows = _extract_rows(filename, data)

    imp = SnapshotImport(
        source=source, filename=filename, row_count=len(rows), uploaded_by=uploaded_by
    )
    db.add(imp)
    db.flush()
    # Wholesale replace per source: the snapshot mirrors the master, it is not history.
    db.execute(delete(ItemSnapshot).where(ItemSnapshot.source == source))
    db.add_all(
        ItemSnapshot(
            source=source,
            item_number=number,
            name=name,
            normalized_name=normalize(name),
            item_group=group,
            import_id=imp.id,
        )
        for number, name, group in rows
    )
    db.commit()
    return imp


def latest_import(db: Session, source: str) -> SnapshotImport | None:
    return db.scalar(
        select(SnapshotImport)
        .where(SnapshotImport.source == source)
        .order_by(SnapshotImport.at.desc())
        .limit(1)
    )


def source_for_factory(db: Session, factory_id: int) -> str:
    factory = db.get(Factory, factory_id)
    return factory.item_source if factory else "D365"


def search_similar(
    db: Session, *, source: str, query: str, limit: int = 8, min_score: float = 0.18
) -> list[tuple[ItemSnapshot, float]]:
    q = normalize(query)
    if len(q) < 3:
        return []
    tokens = [t for t in q.split() if len(t) >= 2][:5]
    if not tokens:
        return []
    stmt = (
        select(ItemSnapshot)
        .where(
            ItemSnapshot.source == source,
            or_(*[ItemSnapshot.normalized_name.like(f"%{t}%") for t in tokens]),
        )
        .limit(3000)
    )
    candidates = db.scalars(stmt).all()
    scored = [(item, similarity(q, item.normalized_name)) for item in candidates]
    scored = [(i, s) for i, s in scored if s >= min_score]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
