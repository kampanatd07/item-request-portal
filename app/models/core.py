from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Request lifecycle statuses. Slice 1 uses up to REJECTED/APPROVED;
# EXPORTED/CREATED/NOTIFIED arrive with slices 5-6.
REQUEST_STATUSES = [
    "submitted",
    "in_review",
    "needs_info",
    "approved",
    "rejected",
    "exported",
    "created",
    "notified",
]


class Factory(Base):
    __tablename__ = "factories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # CBD, APM, APG, ACM
    name: Mapped[str] = mapped_column(String(100))
    # Which item-master snapshot this factory's duplicate check searches against.
    item_source: Mapped[str] = mapped_column(String(10), default="D365")  # CBD | D365
    active: Mapped[bool] = mapped_column(default=True)

    code_systems: Mapped[list["FactoryCodeSystem"]] = relationship(back_populates="factory")


class CodeSystem(Base):
    """One item-code pattern, e.g. D365_STOCK. pattern_template documents the shape;
    actual generation logic arrives in slice 3."""

    __tablename__ = "code_systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # e.g. D365_STOCK
    name_th: Mapped[str] = mapped_column(String(100))
    pattern_template: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(default=True)

    groups: Mapped[list["CodeGroup"]] = relationship(back_populates="system")


class FactoryCodeSystem(Base):
    """Which code systems a factory may request against."""

    __tablename__ = "factory_code_systems"
    __table_args__ = (UniqueConstraint("factory_id", "code_system_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"))
    code_system_id: Mapped[int] = mapped_column(ForeignKey("code_systems.id"))

    factory: Mapped[Factory] = relationship(back_populates="code_systems")
    code_system: Mapped[CodeSystem] = relationship()


class CodeGroup(Base):
    """Selectable group/category per system — editable config, never hardcoded.
    parent_id builds hierarchies (CBD stock: category -> subcategory; D365 806: mould types)."""

    __tablename__ = "code_groups"
    __table_args__ = (UniqueConstraint("code_system_id", "code", "parent_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code_system_id: Mapped[int] = mapped_column(ForeignKey("code_systems.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("code_groups.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(10))  # '800', 'BD', '01' ...
    name: Mapped[str] = mapped_column(String(200))
    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Overrides the system's pattern_template for this group (e.g. SVSP, 806 Mould).
    pattern_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)

    system: Mapped[CodeSystem] = relationship(back_populates="groups")
    parent: Mapped["CodeGroup | None"] = relationship(remote_side="CodeGroup.id")


class ItemRequest(Base):
    __tablename__ = "item_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Requester identity is free-form in slice 1; becomes FK to users when auth lands.
    requester_name: Mapped[str] = mapped_column(String(100))
    requester_email: Mapped[str] = mapped_column(String(200))
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"))
    code_system_id: Mapped[int] = mapped_column(ForeignKey("code_systems.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("code_groups.id"))
    subgroup_id: Mapped[int | None] = mapped_column(ForeignKey("code_groups.id"), nullable=True)

    # Name parts follow the naming convention: ชื่อ / แบรนด์ / รุ่น / ขนาด / ชนิด / สี
    item_name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spec_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    uom: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Export-only fields (slice 4). search_name defaults to a truncation of the
    # composed name; the taxonomy slice replaces the default with a smart value.
    search_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purchase_price: Mapped[str | None] = mapped_column(String(30), nullable=True)
    procurement_category: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="submitted")
    generated_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("export_batches.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    factory: Mapped[Factory] = relationship()
    code_system: Mapped[CodeSystem] = relationship()
    group: Mapped[CodeGroup] = relationship(foreign_keys=[group_id])
    subgroup: Mapped["CodeGroup | None"] = relationship(foreign_keys=[subgroup_id])
    events: Mapped[list["RequestEvent"]] = relationship(
        back_populates="request", order_by="RequestEvent.id"
    )


class SearchTerm(Base):
    """Canonical item-type vocabulary for search names (e.g. BALL BEARING, GASKET).
    Seeded from the real master; grows as procurement promotes new terms."""

    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(60), unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    usage_count: Mapped[int] = mapped_column(default=0)


class Uom(Base):
    """Unit-of-measure options offered in the form (AX-valid values)."""

    __tablename__ = "uoms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(default=True)


class GroupExportMap(Base):
    """Resolves a top-level group to the D365 internal codes an import file needs.
    Seeded with observed values; completed by Peter. Nullable = not yet known."""

    __tablename__ = "group_export_map"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_group_id: Mapped[int] = mapped_column(ForeignKey("code_groups.id"), unique=True)
    item_group_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model_group_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    group_type_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    group: Mapped["CodeGroup"] = relationship()


class ExportBatch(Base):
    """One generated import file for one factory."""

    __tablename__ = "export_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("factories.id"))
    filename: Mapped[str] = mapped_column(String(200))
    item_count: Mapped[int] = mapped_column()
    created_by: Mapped[str] = mapped_column(String(100), default="procurement")
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    factory: Mapped[Factory] = relationship()


class SnapshotImport(Base):
    """Audit of each item-master upload."""

    __tablename__ = "snapshot_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(10))  # CBD | D365
    filename: Mapped[str] = mapped_column(String(300))
    row_count: Mapped[int] = mapped_column()
    uploaded_by: Mapped[str] = mapped_column(String(100), default="procurement")
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemSnapshot(Base):
    """Copy of the item master used for duplicate check + max running lookup.
    Replaced wholesale per source on each upload; later swappable for a live
    AX DB query behind the same service functions."""

    __tablename__ = "item_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(10), index=True)  # CBD | D365
    item_number: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(500))
    normalized_name: Mapped[str] = mapped_column(String(500), index=True)
    item_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("snapshot_imports.id"))


class RequestEvent(Base):
    """Append-only audit trail."""

    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("item_requests.id"))
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))  # submitted / approved / rejected / ...
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    request: Mapped[ItemRequest] = relationship(back_populates="events")
