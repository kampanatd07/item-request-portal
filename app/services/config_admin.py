"""CRUD for the editable reference data behind exports and classification.

Kept deliberately small: list / add / toggle-active for simple lists, and a
field update for the group export mapping. All changes are immediate; these
tables are low-volume config, not transactional data.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeGroup, GroupExportMap, ProcurementCategory, SearchTerm, Uom


class ConfigError(Exception):
    """Config edit error with a user-facing Thai message."""


# --- UOM --------------------------------------------------------------------
def list_uoms(db: Session) -> list[Uom]:
    return list(db.scalars(select(Uom).order_by(Uom.code)))


def add_uom(db: Session, code: str, name: str) -> Uom:
    code = code.strip()
    if not code:
        raise ConfigError("กรุณากรอกรหัสหน่วยนับ")
    if db.scalar(select(Uom).where(Uom.code == code)):
        raise ConfigError(f"หน่วยนับ {code} มีอยู่แล้ว")
    u = Uom(code=code, name=name.strip() or code)
    db.add(u)
    db.commit()
    return u


def toggle_uom(db: Session, uom_id: int) -> None:
    u = db.get(Uom, uom_id)
    if u:
        u.active = not u.active
        db.commit()


# --- Procurement category ---------------------------------------------------
def list_categories(db: Session, source: str | None = None) -> list[ProcurementCategory]:
    stmt = select(ProcurementCategory).order_by(
        ProcurementCategory.source, ProcurementCategory.label
    )
    if source:
        stmt = stmt.where(ProcurementCategory.source == source)
    return list(db.scalars(stmt))


def active_categories(db: Session, source: str) -> list[ProcurementCategory]:
    return list(
        db.scalars(
            select(ProcurementCategory).where(
                ProcurementCategory.source == source, ProcurementCategory.active
            ).order_by(ProcurementCategory.label)
        )
    )


def add_category(db: Session, source: str, label: str) -> ProcurementCategory:
    label = label.strip()
    if source not in ("CBD", "D365"):
        raise ConfigError("แหล่งข้อมูลไม่ถูกต้อง")
    if not label:
        raise ConfigError("กรุณากรอกชื่อ category")
    c = ProcurementCategory(source=source, label=label)
    db.add(c)
    db.commit()
    return c


def toggle_category(db: Session, category_id: int) -> None:
    c = db.get(ProcurementCategory, category_id)
    if c:
        c.active = not c.active
        db.commit()


# --- Search terms -----------------------------------------------------------
def list_terms(db: Session) -> list[SearchTerm]:
    return list(db.scalars(select(SearchTerm).order_by(SearchTerm.term)))


def toggle_term(db: Session, term_id: int) -> None:
    t = db.get(SearchTerm, term_id)
    if t:
        t.active = not t.active
        db.commit()


# --- Group export mapping ---------------------------------------------------
def list_group_maps(db: Session) -> list[tuple[CodeGroup, GroupExportMap | None]]:
    """All top-level groups with their export mapping (or None if unset)."""
    groups = db.scalars(
        select(CodeGroup).where(CodeGroup.parent_id.is_(None)).order_by(
            CodeGroup.code_system_id, CodeGroup.code
        )
    )
    out = []
    for g in groups:
        mp = db.scalar(select(GroupExportMap).where(GroupExportMap.code_group_id == g.id))
        out.append((g, mp))
    return out


def set_group_map(
    db: Session, group_id: int, *, item_group_id: str, model_group_id: str,
    group_type_code: str,
) -> GroupExportMap:
    group = db.get(CodeGroup, group_id)
    if group is None:
        raise ConfigError("ไม่พบหมวด")
    mp = db.scalar(select(GroupExportMap).where(GroupExportMap.code_group_id == group_id))
    if mp is None:
        mp = GroupExportMap(code_group_id=group_id)
        db.add(mp)
    mp.item_group_id = item_group_id.strip() or None
    mp.model_group_id = model_group_id.strip() or None
    mp.group_type_code = group_type_code.strip() or None
    db.commit()
    return mp
