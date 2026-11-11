"""CRUD for the editable reference data behind exports and classification.

Kept deliberately small: list / add / toggle-active for simple lists, and a
field update for the group export mapping. All changes are immediate; these
tables are low-volume config, not transactional data.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CodeGroup,
    GroupExportMap,
    ItemRequest,
    MailDomain,
    ProcurementCategory,
    SearchTerm,
    Uom,
    UomAlias,
)


class ConfigError(Exception):
    """Config edit error with a user-facing Thai message."""


# --- Mail domains (STORY-002) ------------------------------------------------
# ASCII labels of letters, digits and inner hyphens, at least two labels.
_DOMAIN_RE = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def list_mail_domains(db: Session) -> list[MailDomain]:
    return list(db.scalars(select(MailDomain).order_by(MailDomain.domain)))


def active_mail_domains(db: Session) -> set[str]:
    return set(db.scalars(select(MailDomain.domain).where(MailDomain.active)))


def add_mail_domain(db: Session, domain: str) -> MailDomain:
    domain = (domain or "").strip().lower().removeprefix("@")
    if not _DOMAIN_RE.fullmatch(domain):
        raise ConfigError("รูปแบบโดเมนไม่ถูกต้อง เช่น carabao.co.th (ไม่ต้องใส่ @)")
    if db.scalar(select(MailDomain).where(MailDomain.domain == domain)):
        raise ConfigError(f"โดเมน {domain} มีอยู่แล้ว")
    d = MailDomain(domain=domain)
    db.add(d)
    db.commit()
    return d


def toggle_mail_domain(db: Session, domain_id: int) -> None:
    d = db.get(MailDomain, domain_id)
    if d:
        d.active = not d.active
        db.commit()


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


def canonical_uom(db: Session, raw: str | None) -> str | None:
    """Normalize a raw UOM string to its canonical code.
    Resolution order: exact code match -> alias match (case-insensitive) ->
    unique case-insensitive code match. Ambiguous or unknown input is returned
    as-is — never guess between look-alikes like Job vs JOB."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if db.scalar(select(Uom).where(Uom.code == raw, Uom.active)):
        return raw
    alias = db.scalar(select(UomAlias).where(UomAlias.alias == raw.lower()))
    if alias:
        return alias.uom.code
    matches = list(
        db.scalars(select(Uom).where(func.lower(Uom.code) == raw.lower(), Uom.active))
    )
    if len(matches) == 1:
        return matches[0].code
    return raw


def merge_uoms(db: Session, source_id: int, target_id: int) -> Uom:
    """Merge source UOM into target: source becomes an alias of target, is
    deactivated, its aliases are re-pointed, and existing requests using the
    source code are rewritten so old data is cleaned too."""
    if source_id == target_id:
        raise ConfigError("เลือกหน่วยต้นทางกับปลายทางให้ต่างกัน")
    source, target = db.get(Uom, source_id), db.get(Uom, target_id)
    if source is None or target is None:
        raise ConfigError("ไม่พบหน่วยนับ")

    for alias in list(source.aliases):
        alias.uom_id = target.id
    if not db.scalar(select(UomAlias).where(UomAlias.alias == source.code.lower())):
        db.add(UomAlias(alias=source.code.lower(), uom_id=target.id))
    source.active = False

    for req in db.scalars(select(ItemRequest).where(ItemRequest.uom == source.code)):
        req.uom = target.code
    db.commit()
    return target


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


# --- Thai names and hints of the central categories (STORY-019) -------------

def list_thai_labels(db: Session) -> list[CodeGroup]:
    """Central groups, each followed by its sub-categories, in code order."""
    from app.models import CodeSystem

    central = db.scalar(select(CodeSystem).where(CodeSystem.code == "CENTRAL"))
    if central is None:
        return []
    rows = db.scalars(
        select(CodeGroup).where(CodeGroup.code_system_id == central.id)
    ).all()
    groups = sorted((g for g in rows if g.parent_id is None), key=lambda g: g.code)
    out: list[CodeGroup] = []
    for g in groups:
        out.append(g)
        out.extend(sorted((s for s in rows if s.parent_id == g.id), key=lambda s: s.code))
    return out


def set_thai_label(db: Session, group_id: int, *, name_th: str, hint_th: str) -> CodeGroup:
    """Set or clear (empty) a category's Thai name and hint. Display only."""
    from app.services.thai_labels import HINT_TH_MAX, NAME_TH_MAX, LabelError, clean_label

    group = db.get(CodeGroup, group_id)
    if group is None or group not in list_thai_labels(db):
        raise ConfigError("ไม่พบหมวด")
    try:
        name = clean_label(name_th, NAME_TH_MAX, "ชื่อไทย")
        hint = clean_label(hint_th, HINT_TH_MAX, "ตัวอย่าง")
    except LabelError as e:
        raise ConfigError(str(e)) from e
    group.name_th, group.hint_th = name, hint
    db.commit()
    return group
