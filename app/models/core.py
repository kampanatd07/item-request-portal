from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    code: Mapped[str] = mapped_column(String(10))  # '900', '01', 'BD' ...
    name: Mapped[str] = mapped_column(String(200))
    # Group-standard naming prefix for sub-categories, e.g. 'BEARING'
    # (used as the [CATEGORY] segment of the product name).
    name_prefix: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 'Item' | 'Service' — from the group taxonomy, drives export defaults.
    product_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    # item_name is COMPOSED from (base ชื่อเรียก + brand + model + size + variant)
    # by services/naming.py — requesters never type the final name directly.
    item_name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(100), nullable=True)  # ชนิด/สี
    spec_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who really asked, when Procurement submits on someone's behalf
    # (STORY-002): the email, if given, receives the notification emails.
    originator_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    originator_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
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


class RunningRegister(Base):
    """The central running-number register — one counter per Category+Sub pair.

    The group's handover flags 'ทะเบียนเลขรันกลาง ยังไม่มีเจ้าของ' as the risk that
    would make codes collide within the first month. This table IS that owner:
    numbers are only ever issued by incrementing a row here, inside the same
    transaction that stamps the request.
    """

    __tablename__ = "running_register"
    __table_args__ = (UniqueConstraint("group_code", "sub_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_code: Mapped[str] = mapped_column(String(3))
    sub_code: Mapped[str] = mapped_column(String(2))
    last_running: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
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

    aliases: Mapped[list["UomAlias"]] = relationship(back_populates="uom")


class UomAlias(Base):
    """Alternative spellings that normalize to a canonical UOM (job -> Job).
    Created by the admin merge tool — never auto-merged, because look-alike
    codes (Job vs JOB) can be legitimately different per AX environment."""

    __tablename__ = "uom_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(30), unique=True)  # stored lowercase
    uom_id: Mapped[int] = mapped_column(ForeignKey("uoms.id"))

    uom: Mapped[Uom] = relationship(back_populates="aliases")


class ProcurementCategory(Base):
    """Procurement Category options for the import files, scoped per source.
    Label is embedded verbatim into the export (e.g. '54050102 Computer expenses')."""

    __tablename__ = "procurement_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(10))  # CBD | D365
    label: Mapped[str] = mapped_column(String(200))
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
    source: Mapped[str] = mapped_column(String(10), index=True)  # CBD | D365 | CENTRAL
    item_number: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(500))
    normalized_name: Mapped[str] = mapped_column(String(500), index=True)
    item_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Central taxonomy labels, present when the row came from the classified
    # master (New_Item_Master) or from a procurement correction. These make the
    # snapshot a training set for category suggestion, not just a dup index.
    group_code: Mapped[str | None] = mapped_column(String(3), nullable=True, index=True)
    sub_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
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
    # The event this one is about: a notified / notify_failed event points at
    # the status change it announced (STORY-002), so "already sent?" is a
    # column lookup, never a search through detail text.
    ref_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("request_events.id", name="fk_request_events_ref_event_id"),
        nullable=True, index=True)

    request: Mapped[ItemRequest] = relationship(back_populates="events")


# Account roles, lowest to highest. Administrator passes every Procurement check.
ROLES = ["requester", "procurement", "administrator"]


class Account(Base):
    """One login to the portal. Deactivated, never deleted; email never changes."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "role IN ('requester', 'procurement', 'administrator')", name="ck_accounts_role"
        ),
        # A Requester belongs to exactly one Plant; other Roles choose it per request.
        CheckConstraint(
            "role != 'requester' OR factory_id IS NOT NULL", name="ck_accounts_requester_plant"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lowercased
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    factory_id: Mapped[int | None] = mapped_column(ForeignKey("factories.id"), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    # Bumped on password change / deactivation so every existing session dies.
    session_version: Mapped[int] = mapped_column(default=1)
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    factory: Mapped[Factory | None] = relationship()


# Why a Central Code was thrown away (STORY-010).
RETIRE_REASONS = ["reissued", "overridden", "rejected", "skipped"]


class RetiredCode(Base):
    """A Central Code that was issued and then thrown away: never usable again.

    Governance v1 §3: an issued number is used forever. The unique `code` is the
    DB-level guarantee, so nothing has to parse event text to know it.
    """

    __tablename__ = "retired_codes"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('reissued', 'overridden', 'rejected', 'skipped')",
            name="ck_retired_codes_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(11), unique=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("item_requests.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(254))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MailDomain(Base):
    """An email domain an originator email may use (STORY-002).

    Reference data editable on the Settings page, so a new company domain needs
    no deploy. Deliberately not tied to a Plant.
    """

    __tablename__ = "mail_domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(253), unique=True)  # stored lower-case
    active: Mapped[bool] = mapped_column(default=True)

