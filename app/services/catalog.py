from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeGroup, CodeSystem, Factory, FactoryCodeSystem


def list_factories(db: Session) -> list[Factory]:
    return list(db.scalars(select(Factory).where(Factory.active).order_by(Factory.code)))


def systems_for_factory(db: Session, factory_id: int) -> list[CodeSystem]:
    stmt = (
        select(CodeSystem)
        .join(FactoryCodeSystem, FactoryCodeSystem.code_system_id == CodeSystem.id)
        .where(FactoryCodeSystem.factory_id == factory_id, CodeSystem.active)
        .order_by(CodeSystem.code)
    )
    return list(db.scalars(stmt))


def groups_for_system(db: Session, code_system_id: int) -> list[CodeGroup]:
    stmt = (
        select(CodeGroup)
        .where(
            CodeGroup.code_system_id == code_system_id,
            CodeGroup.parent_id.is_(None),
            CodeGroup.active,
        )
        .order_by(CodeGroup.code)
    )
    return list(db.scalars(stmt))


def subgroups_for_group(db: Session, group_id: int) -> list[CodeGroup]:
    stmt = (
        select(CodeGroup)
        .where(CodeGroup.parent_id == group_id, CodeGroup.active)
        .order_by(CodeGroup.code)
    )
    return list(db.scalars(stmt))
