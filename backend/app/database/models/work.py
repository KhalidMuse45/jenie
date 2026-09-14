"""The work tree and its history.

Two tables. ``work_items`` is the mutable present -- what exists, who owns it,
where it stands. ``task_events`` is the immutable past, appended to on every
change and never updated.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import TaskEventType, WorkItemStatus, WorkItemType


class WorkItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "work_items"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # Composite reference below keeps the parent in the same organization.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    type: Mapped[WorkItemType] = mapped_column(
        Enum(WorkItemType, native_enum=False, length=20), nullable=False
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Unowned work is legitimate: an initiative can exist before anyone is
    # responsible for it.
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    status: Mapped[WorkItemStatus] = mapped_column(
        Enum(WorkItemStatus, native_enum=False, length=20),
        nullable=False,
        server_default=text(f"'{WorkItemStatus.ACTIVE.value}'"),
    )

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    short_code: Mapped[str] = mapped_column(String(16), nullable=False)

    # Optimistic concurrency. Two people acting on the same item within a moment
    # of each other must not silently overwrite one another.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_work_items_id_organization_id"),
        UniqueConstraint(
            "organization_id", "short_code", name="uq_work_items_organization_id_short_code"
        ),
        # Parent, owner and creator all have to belong to the same organization
        # as the item itself. Single-column references could not say that.
        ForeignKeyConstraint(
            ["parent_id", "organization_id"],
            ["work_items.id", "work_items.organization_id"],
            name="fk_work_items_parent_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_work_items_owner_same_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_work_items_creator_same_organization",
            ondelete="RESTRICT",
        ),
        # Only an initiative may be rootless. Which type may parent which is
        # enforced in the domain service, where the parent row is available.
        CheckConstraint(
            "type = 'INITIATIVE' OR parent_id IS NOT NULL",
            name="only_initiatives_are_roots",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_is_not_self"),
        Index("ix_work_items_organization_id", "organization_id"),
        Index("ix_work_items_parent_id", "parent_id"),
        Index("ix_work_items_owner_membership_id", "owner_membership_id"),
    )

    def __repr__(self) -> str:
        return f"<WorkItem {self.short_code} {self.type} {self.title!r}>"


class TaskEvent(UUIDPrimaryKeyMixin, Base):
    """One entry in a work item's history.

    Append-only: no updated_at, and nothing in the codebase updates these rows.
    """

    __tablename__ = "task_events"

    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )

    # Null when Jenie itself acted, for example a scheduled cancellation.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL"), nullable=True
    )

    event_type: Mapped[TaskEventType] = mapped_column(
        Enum(TaskEventType, native_enum=False, length=30), nullable=False
    )

    # Mapped to the column name the spec uses; the attribute is renamed because
    # ``metadata`` is taken by SQLAlchemy's declarative base.
    payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_task_events_work_item_id", "work_item_id"),
        Index("ix_task_events_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<TaskEvent {self.event_type} work_item={self.work_item_id}>"
