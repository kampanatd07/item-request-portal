"""Item-master snapshot: import + duplicate search.

Search is implemented portably (token prefilter in SQL + trigram scoring in
Python) so it runs identically on SQLite (dev/tests) and Postgres. If volume
grows or latency hurts, swap the internals for pg_trgm — callers won't change.
"""

import csv
import io
import re
import unicodedata

from openpyxl import load_workbook
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import Factory, ItemSnapshot, SnapshotImport

SOURCES = ("CBD", "D365")


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
    db: Session, *, source: str, filename: str, data: bytes, uploaded_by: str = "procurement"
) -> SnapshotImport:
    if source not in SOURCES:
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
